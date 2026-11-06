"""本地端到端功能测试：真实 uvicorn HTTP + SQLite + 本地对象存储 + seed0 权重。

启动独立服务进程后，按真实接口顺序验证：
登录/RBAC -> 建数据集 -> ZIP 导入 -> 标注领取/驳回/通过 -> 冻结版本与 manifest
-> 注册并启用模型 -> 建档/检查/领取 -> 真实 TransUNet 推理 -> 医生复核
-> 起草/提交/签发报告 -> PDF 与审计统计。

任务通过 outbox + ``app.cli dispatch-once``（TASK_EAGER=true）执行，不使用 TestClient。

用法：
    python backend/scripts/e2e_local.py
    python backend/scripts/e2e_local.py --keep --evidence docs/evidence/real-e2e-local.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "DemoPassword!123"
LABELS = ("benign", "malignant", "normal")
PER_CLASS = 3
DATASET_DIR = ROOT / "transunet" / "data" / "Dataset_BUSI_with_GT"


def log(message):
    print(message, flush=True)


def check(response, status, label):
    if response.status_code != status:
        raise AssertionError(f"{label}: 期望 {status}，实际 {response.status_code}，响应 {response.text[:800]}")
    return response.json()["data"] if response.content else None


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_module(env, *args, timeout=900):
    result = subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} 失败（{result.returncode}）\nstdout:\n{result.stdout[-3000:]}"
            f"\nstderr:\n{result.stderr[-3000:]}"
        )
    return result.stdout


def synthetic_pngs():
    """没有 BUSI 数据时的确定性替代影像，仍满足导入规范。"""
    files = []
    for label in LABELS:
        for index in range(1, PER_CLASS + 1):
            image = Image.new("L", (256, 192), 35 + index * 8)
            draw = ImageDraw.Draw(image)
            draw.ellipse((60, 50, 190, 145), fill=120 + index * 6)
            image = image.convert("RGB")
            mask = Image.new("L", image.size, 0)
            if label != "normal":
                ImageDraw.Draw(mask).ellipse((70, 60, 180, 135), fill=255)
            image_bytes, mask_bytes = io.BytesIO(), io.BytesIO()
            image.save(image_bytes, "PNG")
            mask.save(mask_bytes, "PNG")
            name = f"{label} ({index})"
            files.append((f"{label}/{name}.png", image_bytes.getvalue()))
            files.append((f"{label}/{name}_mask.png", mask_bytes.getvalue()))
    return files, "synthetic"


def busi_files():
    files = []
    for label in LABELS:
        for index in range(1, PER_CLASS + 1):
            name = f"{label} ({index})"
            image = DATASET_DIR / label / f"{name}.png"
            mask = DATASET_DIR / label / f"{name}_mask.png"
            if not image.is_file() or not mask.is_file():
                return synthetic_pngs()
            files.append((f"{label}/{name}.png", image.read_bytes()))
            files.append((f"{label}/{name}_mask.png", mask.read_bytes()))
    return files, "real BUSI"


def archive_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return output.getvalue()


def login(api, username):
    data = check(api.post("/auth/login", json={"username": username, "password": PASSWORD}), 200, f"登录 {username}")
    return {"Authorization": "Bearer " + data["access_token"]}


def pending_tasks(env):
    run_module(env, "app.cli", "dispatch-once")


def wait_for(fn, env, timeout, description, interval=0.5):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{description} 超时（{timeout}s）")
        time.sleep(interval)
        pending_tasks(env)


def wait_import(api, headers, env, job_id):
    def poll():
        job = check(api.get(f"/imports/{job_id}", headers=headers), 200, "导入进度")
        return job if job["status"] in ("completed", "failed") else None

    return wait_for(poll, env, 180, "ZIP 导入")


def wait_inference(api, headers, env, task_id):
    def poll():
        task = check(api.get(f"/inference-tasks/{task_id}", headers=headers), 200, "推理进度")
        return task if task["status"] in ("succeeded", "failed") else None

    return wait_for(poll, env, 900, "模型推理", interval=0.2)


def annotation_rle(width, height, empty=False):
    if empty:
        return {"size": [height, width], "counts": [width * height]}
    return {"size": [height, width], "counts": [0, width * height]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留运行时目录，便于排查")
    parser.add_argument("--evidence", type=Path, help="将结果写入证据 JSON")
    args = parser.parse_args()

    started = time.monotonic()
    run_dir = ROOT / ".runtime" / "e2e" / datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT)]),
            "DATABASE_URL": "sqlite:///" + (run_dir / "e2e.db").as_posix(),
            "STORAGE_BACKEND": "local",
            "STORAGE_DIR": str(run_dir / "objects"),
            "WORK_DIR": str(run_dir / "work"),
            "JWT_SECRET": "e2e-local-only-secret-0123456789abcdef",
            "RATE_LIMIT_BACKEND": "memory",
            "TASK_EAGER": "true",
            "DEVICE": "cpu",
            "PUBLIC_API_URL": base_url,
        }
    )

    server_log = (run_dir / "server.log").open("wb")
    server = None
    evidence = {}
    passed = False
    try:
        log("[1/9] 初始化数据库与演示账号")
        run_module(env, "alembic", "-c", "backend/alembic.ini", "upgrade", "head", timeout=180)
        run_module(env, "app.cli", "init-storage", timeout=120)
        run_module(env, "app.cli", "seed-demo", timeout=120)

        log(f"[2/9] 启动 uvicorn: {base_url}")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        api = httpx.Client(base_url=base_url + "/api/v1", timeout=120)
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError("服务进程提前退出：\n" + (run_dir / "server.log").read_text(errors="replace"))
            try:
                if api.get("/readyz").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("服务就绪超时")
            time.sleep(0.5)

        if api.get("/images").status_code != 401:
            raise AssertionError("未登录访问 /images 应返回 401")

        headers = {name: login(api, name) for name in ("admin", "data_engineer", "annotator", "screener", "reviewer")}
        admin = headers["admin"]

        if api.post("/datasets", headers=headers["annotator"], json={"name": "denied"}).status_code != 403:
            raise AssertionError("标注员创建数据集应返回 403")
        if api.get("/users", headers=headers["screener"]).status_code != 403:
            raise AssertionError("筛查医生读取用户列表应返回 403")
        if api.post("/inference-tasks", headers=headers["reviewer"], json={"image_id": "x"}).status_code != 403:
            raise AssertionError("审核员发起推理应返回 403")

        log("[3/9] 导入 ZIP（含参考掩膜）")
        files, image_source = busi_files()
        dataset = check(api.post("/datasets", headers=headers["data_engineer"], json={"name": "e2e-local"}), 201, "新建数据集")
        upload = api.post(
            f"/datasets/{dataset['id']}/imports",
            headers={**headers["data_engineer"], "Idempotency-Key": "e2e-import"},
            files={"file": ("e2e.zip", archive_bytes(files), "application/zip")},
        )
        job_id = check(upload, 202, "提交导入")["job_id"]
        job = wait_import(api, headers["data_engineer"], env, job_id)
        if job["status"] != "completed" or job["success"] != PER_CLASS * len(LABELS) or job["failed"] != 0:
            raise AssertionError(f"导入结果异常：{job}")
        images = check(api.get("/images", headers=admin, params={"dataset_id": dataset["id"], "page_size": 100}), 200, "影像列表")
        if len(images) != PER_CLASS * len(LABELS):
            raise AssertionError(f"影像数量异常：{len(images)}")

        signer = images[0]
        download = api.get(signer["thumbnail_url"])
        if download.status_code != 200 or not download.content.startswith(b"\x89PNG"):
            raise AssertionError("签名缩略图下载失败")
        forged = signer["thumbnail_url"][:-4] + "AAAA"
        if api.get(forged).status_code != 403:
            raise AssertionError("篡改签名后的下载链接应返回 403")
        preview = api.get(signer["preview_url"])
        if preview.status_code != 200:
            raise AssertionError("原始尺寸预览下载失败")
        with Image.open(io.BytesIO(preview.content)) as preview_image:
            if preview_image.size != (signer["width"], signer["height"]):
                raise AssertionError(
                    f"预览尺寸 {preview_image.size} 与影像元数据 {(signer['width'], signer['height'])} 不一致"
                )

        log("[4/9] 标注：领取 -> 提交 -> 驳回 -> 重存 -> 通过")
        target = next(item for item in images if item["class_label"] == "benign")
        task_id = check(
            api.post("/annotation-tasks", headers=admin, json={"image_ids": [target["id"]]}), 201, "创建标注任务"
        )["task_ids"][0]
        check(api.post(f"/annotation-tasks/{task_id}/claim", headers=headers["annotator"]), 200, "领取标注任务")
        payload = {
            "image_id": target["id"],
            "mask_rle": annotation_rle(target["width"], target["height"]),
            "source": "manual",
        }
        annotation = check(api.post("/annotations", headers=headers["annotator"], json=payload), 201, "保存标注")
        check(api.post(f"/annotations/{annotation['id']}/submit", headers=headers["annotator"]), 200, "提交标注")
        check(
            api.post(
                f"/annotations/{annotation['id']}/reviews",
                headers=headers["reviewer"],
                json={"decision": "reject", "comment": "边缘需要重新修整"},
            ),
            200,
            "驳回标注",
        )
        revised = check(
            api.post(
                "/annotations",
                headers=headers["annotator"],
                json={
                    "image_id": target["id"],
                    "mask_rle": annotation_rle(target["width"], target["height"], empty=True),
                    "is_empty": True,
                    "source": "manual",
                },
            ),
            201,
            "重存标注",
        )
        check(api.post(f"/annotations/{revised['id']}/submit", headers=headers["annotator"]), 200, "重新提交标注")
        approved = check(
            api.post(
                f"/annotations/{revised['id']}/reviews",
                headers=headers["reviewer"],
                json={"decision": "approve", "comment": "复核通过"},
            ),
            200,
            "通过标注",
        )
        if approved["status"] != "approved" or approved["version"] != 3:
            raise AssertionError(f"标注审核状态异常：{approved['status']}/{approved['version']}")

        log("[5/9] 冻结数据集版本并校验 manifest")
        version = check(
            api.post(
                "/dataset-versions",
                headers=headers["data_engineer"],
                json={
                    "dataset_id": dataset["id"],
                    "version": "e2e-v1",
                    "ratios": {"train": 0.34, "val": 0.33, "test": 0.33},
                },
            ),
            201,
            "创建数据集版本",
        )
        frozen = check(api.post(f"/dataset-versions/{version['id']}/freeze", headers=headers["data_engineer"]), 200, "冻结版本")
        if sum(frozen["counts"].values()) != PER_CLASS * len(LABELS):
            raise AssertionError(f"冻结计数异常：{frozen['counts']}")
        if api.get(f"/dataset-versions/{version['id']}/manifest", headers=headers["annotator"]).status_code != 403:
            raise AssertionError("标注员导出 manifest 应返回 403")
        manifest_response = api.get(
            f"/dataset-versions/{version['id']}/manifest", headers=admin, follow_redirects=True
        )
        if manifest_response.status_code != 200:
            raise AssertionError(f"导出 manifest: 实际 {manifest_response.status_code}")
        manifest = manifest_response.json()
        if len(manifest["items"]) != PER_CLASS * len(LABELS):
            raise AssertionError("manifest 条目数不符")
        frozen_target = next(item for item in manifest["items"] if item["image_id"] == target["id"])
        if frozen_target["annotation_version"] != 3:
            raise AssertionError(f"manifest 未引用最新 approved 标注：{frozen_target['annotation_version']}")

        log("[6/9] 注册并启用 seed0 模型")
        registry = json.loads((ROOT / "algo" / "models" / "registry.json").read_text(encoding="utf-8"))
        record = registry["models"][0]
        weights = ROOT / record["weights_path"]
        if not weights.is_file():
            raise FileNotFoundError(f"缺少真实权重：{weights}")
        key = f"models/{record['weights_sha256']}.pth"
        stored = run_dir / "objects" / "bidlsp-model" / key
        stored.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(weights, stored)
        except OSError:
            shutil.copyfile(weights, stored)
        model = check(api.post("/models", headers=admin, json={"name": "transunet"}), 201, "注册模型")
        version_body = {
            "version": record["version"],
            "weights_key": key,
            "weights_sha256": record["weights_sha256"],
            "config": record["config"],
            "metrics": record["metrics"],
        }
        model_version = check(api.post(f"/models/{model['id']}/versions", headers=admin, json=version_body), 201, "注册模型版本")
        check(api.post(f"/model-versions/{model_version['id']}/activate", headers=admin), 200, "启用模型版本")
        listed = check(api.get("/models", headers=admin), 200, "模型列表")[0]
        if listed["active_version"]["id"] != model_version["id"] or not any(
            item["id"] == model_version["id"] for item in listed["versions"]
        ):
            raise AssertionError("模型列表未返回版本与启用版本")

        log("[7/9] 建档、领取筛查任务并执行真实推理（CPU）")
        patient = check(
            api.post("/patients", headers=headers["screener"], json={"gender": "F", "birth_year": 1980}), 201, "创建患者"
        )
        study = check(
            api.post(
                "/studies",
                headers=headers["screener"],
                json={"patient_id": patient["id"], "study_date": date.today().isoformat(), "image_ids": [target["id"]]},
            ),
            201,
            "创建检查",
        )
        screen = check(api.post("/screen-tasks", headers=headers["screener"], json={"study_id": study["id"]}), 201, "创建筛查任务")
        check(api.post(f"/screen-tasks/{screen['id']}/claim", headers=headers["screener"]), 200, "领取筛查任务")
        inference_request = {**headers["screener"], "Idempotency-Key": "e2e-inference"}
        first = check(
            api.post("/inference-tasks", headers=inference_request, json={"image_id": target["id"]}), 202, "提交推理"
        )
        replay = check(
            api.post("/inference-tasks", headers=inference_request, json={"image_id": target["id"]}), 202, "重复推理请求"
        )
        if replay["task_id"] != first["task_id"]:
            raise AssertionError("幂等键未复用原推理任务")
        inference = wait_inference(api, headers["screener"], env, first["task_id"])
        if inference["status"] != "succeeded" or not inference["result"]:
            raise AssertionError(f"推理失败：{inference.get('error')}")
        result = inference["result"]
        mask = api.get(result["mask_url"])
        if mask.status_code != 200 or not mask.content.startswith(b"\x89PNG"):
            raise AssertionError("推理掩膜签名下载失败")

        log("[8/9] 医生复核并起草/提交/签发报告")
        check(api.post(f"/studies/{study['id']}/reviews", headers=headers["screener"], json={"decision": "accept"}), 200, "复核通过")
        template = check(api.get("/report-templates", headers=headers["screener"]), 200, "报告模板")[0]
        report = check(
            api.post(
                "/reports",
                headers=headers["screener"],
                json={
                    "study_id": study["id"],
                    "template_id": template["id"],
                    "inference_result_id": result["id"],
                    "content": {
                        "findings": "科研样例：影像可见低回声区，掩膜已由医生复核。",
                        "impression": "模型提示病灶区域，仅供研究参考。",
                        "recommendation": "建议结合其他检查，由专业医师评估。",
                    },
                },
            ),
            201,
            "起草报告",
        )
        preview = api.get(f"/reports/{report['id']}/pdf", headers=headers["screener"], follow_redirects=True)
        if preview.status_code != 200:
            raise AssertionError(
                f"未签发报告 PDF 预览失败：{preview.status_code}，"
                f"redirects={[item.status_code for item in preview.history]}，响应 {preview.text[:500]}"
            )
        preview_text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(preview.content)).pages)
        if "未签发" not in preview_text:
            raise AssertionError("未签发预览缺少水印")
        check(api.post(f"/reports/{report['id']}/submit", headers=headers["screener"]), 200, "提交报告")
        signed = check(
            api.post(
                f"/reports/{report['id']}/sign",
                headers=headers["reviewer"],
                json={"decision": "sign", "comment": "已核对科研样例"},
            ),
            200,
            "签发报告",
        )
        if signed["status"] != "signed":
            raise AssertionError("报告未签发")
        if api.post(f"/reports/{report['id']}/sign", headers=headers["reviewer"], json={"decision": "sign"}).status_code != 409:
            raise AssertionError("重复签发应返回 409")
        pdf = api.get(f"/reports/{report['id']}/pdf", headers=admin, follow_redirects=True)
        pdf_text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
        if "仅供科研/教学使用，不作为临床诊断依据" not in pdf_text or "科研样例" not in pdf_text:
            raise AssertionError("已签发 PDF 缺少免责声明或报告内容")

        log("[9/9] 统计与审计校验")
        overview = check(api.get("/stats/overview", headers=admin), 200, "统计总览")
        if overview["images"] != PER_CLASS * len(LABELS) or overview["reports_signed"] != 1:
            raise AssertionError(f"统计不符：{overview}")
        audit = check(api.get("/audit-logs", headers=admin, params={"page_size": 100}), 200, "审计日志")
        actions = {entry["action"] for entry in audit}
        missing = {"data.import.finish", "annotation.review", "inference.finish", "report.sign"} - actions
        if missing:
            raise AssertionError(f"缺少审计事件：{sorted(missing)}")

        duration = round(time.monotonic() - started, 1)
        evidence = {
            "date": date.today().isoformat(),
            "mode": "uvicorn 真实 HTTP + SQLite + 本地对象存储 + seed0 真实权重",
            "script": "backend/scripts/e2e_local.py",
            "result": "PASS",
            "duration_seconds": duration,
            "image_source": image_source,
            "flow": [
                "login / RBAC",
                "create dataset",
                "upload ZIP with reference masks",
                "outbox import via dispatch-once",
                "annotation claim / reject / approve",
                "freeze dataset version + manifest",
                "register and activate seed0 model",
                "patient / study / screen task",
                "real CPU inference",
                "study review accept",
                "draft / submit / sign report",
                "PDF + stats + audit",
            ],
            "dataset": {
                "images": len(images),
                "splits": frozen["counts"],
                "manifest_items": len(manifest["items"]),
            },
            "model": {
                "version": model_version["version"],
                "active": True,
                "versions_listed": len(listed["versions"]),
            },
            "inference": {
                "status": inference["status"],
                "elapsed_ms": result["elapsed_ms"],
                "lesion_area_ratio": result["lesion_area_ratio"],
                "quality_flags": result["quality_flags"],
                "mask_size": result["mask_rle"]["size"],
            },
            "report": {"status": signed["status"], "pdf_bytes": len(pdf.content)},
            "stats": overview,
            "audit_actions": sorted(actions),
        }
        passed = True
        log("PASS: 登录 -> 导入 -> 标注审核 -> 冻结 -> 真实推理 -> 复核 -> 签发 -> PDF/审计")
        log(f"用时 {duration}s；运行时目录 {run_dir}")
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log(f"证据已写入 {args.evidence}")
    finally:
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
        server_log.close()
        if passed and not args.keep:
            shutil.rmtree(run_dir, ignore_errors=True)
        elif not passed:
            log(f"运行日志与临时数据保留在 {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint must surface failures
        log(f"FAIL: {exc}")
        sys.exit(1)
