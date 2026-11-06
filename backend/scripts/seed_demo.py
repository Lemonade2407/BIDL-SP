"""向运行中的 Compose 环境灌入真实 BUSI 数据与完整演示闭环。

流程：
1. 通过 init 容器导入本地 BUSI 目录（779 张，严格 SHA256 去重）
2. 注册 3 个真实 TransUNet 权重并启用 seed0
3. 创建并冻结数据集版本
4. 生成标注任务：一条完整审核通过、一条草稿、两条待领取
5. 生成筛查数据：已签发报告、待审核报告、待医生复核、待领取任务
6. 执行真实 CPU 推理

前置：Docker Compose 已启动；本地存在 transunet/data/Dataset_BUSI_with_GT 与 transunet/results/*.pth。
用法：
    python backend/scripts/seed_demo.py
    python backend/scripts/seed_demo.py --skip-import --skip-models
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "transunet" / "data" / "Dataset_BUSI_with_GT"
DEMO_PASSWORD = "DemoPassword!123"
COMPOSE = ["docker", "compose", "--env-file", "deploy/.env", "-f", "deploy/docker-compose.yml"]


def log(message):
    print(message, flush=True)


def run_cli(args, mount=None, timeout=3600):
    command = [*COMPOSE, "run", "--rm"]
    if mount:
        command += ["-v", mount]
    command += ["init", "python", "-m", "app.cli", *args]
    log("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} 失败（{result.returncode}）\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
    return result.stdout


def last_json(output):
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


class Api:
    def __init__(self, base_url):
        self.client = httpx.Client(base_url=base_url, timeout=120)

    def call(self, method, path, token=None, expect=200, **kwargs):
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = "Bearer " + token
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code != expect:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:800]}")
        return response.json()["data"] if response.content else None

    def login(self, username):
        payload = {"username": username, "password": DEMO_PASSWORD}
        for _ in range(3):
            response = self.client.post("/auth/login", json=payload)
            if response.status_code == 200:
                return response.json()["data"]["access_token"]
            if response.status_code == 429:
                log("登录限流，等待 61 秒后重试…")
                time.sleep(61)
                continue
            raise RuntimeError(f"登录 {username} 失败：{response.status_code} {response.text[:300]}")
        raise RuntimeError(f"登录 {username} 多次限流")

    def wait_inference(self, token, task_id, timeout=900):
        deadline = time.monotonic() + timeout
        while True:
            task = self.call("GET", f"/inference-tasks/{task_id}", token)
            if task["status"] in ("succeeded", "failed"):
                return task
            if time.monotonic() >= deadline:
                raise TimeoutError(f"推理 {task_id} 超时")
            time.sleep(2)


def pick_images(api, token, label, count, used):
    rows = api.call("GET", "/images", token, params={"class_label": label, "page_size": 100})
    picked = [item for item in rows if item["id"] not in used and not item.get("study_id")]
    if len(picked) < count:
        raise RuntimeError(f"{label} 可用影像不足：需要 {count}，实际 {len(picked)}")
    return picked[:count]


def rle(width, height):
    return {"size": [height, width], "counts": [0, width * height]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()

    api = Api(args.api_url)
    deadline = time.monotonic() + 60
    while True:
        try:
            if api.client.get("/readyz").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("API 未就绪，请先启动 docker compose")
        time.sleep(1)

    tokens = {name: api.login(name) for name in ("admin", "data_engineer", "annotator", "screener", "reviewer")}
    admin = tokens["admin"]

    total = api.client.get("/images", headers={"Authorization": "Bearer " + admin}, params={"page_size": 1})
    image_total = total.json()["meta"]["total"]
    if not args.skip_import and image_total < 700:
        if not args.dataset_dir.is_dir():
            raise SystemExit(f"缺少本地 BUSI 目录：{args.dataset_dir}")
        log(f"[1/6] 导入真实 BUSI 目录（当前影像 {image_total} 张）")
        output = run_cli(
            ["import-directory", "/dataset", "--dataset", "BUSI"],
            mount=f"{args.dataset_dir.as_posix()}:/dataset:ro",
        )
        summary = last_json(output)
        log(
            "      导入完成："
            f"success={summary.get('success')} duplicate={summary.get('duplicate')} failed={summary.get('failed')}"
        )
    else:
        log(f"[1/6] 跳过导入（现有影像 {image_total} 张）")

    if not args.skip_models:
        log("[2/6] 注册三份真实权重（SHA256 校验）")
        run_cli(["seed-models", "--root", "/assets"], mount=f"{ROOT.as_posix()}:/assets:ro")
        log("      权重已注册")
    else:
        log("[2/6] 跳过模型注册")

    datasets = api.call("GET", "/datasets", admin)
    dataset = next((item for item in datasets if item["name"] == "BUSI"), None)
    if not dataset:
        raise RuntimeError("未找到 BUSI 数据集")
    versions = api.call(
        "GET", "/dataset-versions", admin, params={"dataset_id": dataset["id"], "page_size": 100}
    )
    frozen = next((item for item in versions if item["status"] == "frozen"), None)
    if frozen:
        log(f"[3/6] 复用已冻结版本 {frozen['version']}：{frozen.get('counts')}")
    else:
        log("[3/6] 创建并冻结数据集版本")
        version = api.call(
            "POST",
            "/dataset-versions",
            tokens["data_engineer"],
            expect=201,
            json={"dataset_id": dataset["id"], "version": "demo-v1"},
        )
        frozen = api.call(
            "POST", f"/dataset-versions/{version['id']}/freeze", tokens["data_engineer"]
        )
        log(f"      冻结完成：{frozen['counts']}")

    models = api.call("GET", "/models", admin)
    if not models:
        raise RuntimeError("没有已注册模型，请先执行 seed-models")
    model = models[0]
    active = next((item for item in model["versions"] if item["status"] == "active"), None)
    if not active:
        seed0 = next((item for item in model["versions"] if item["version"] == "s256rgb-seed0"), None)
        if not seed0:
            raise RuntimeError("缺少 s256rgb-seed0 版本")
        active = api.call("POST", f"/model-versions/{seed0['id']}/activate", admin)
    log(f"[4/6] 在线模型：{active['version']}")

    used = set()
    tasks_total = api.client.get(
        "/annotation-tasks", headers={"Authorization": "Bearer " + admin}, params={"page_size": 1}
    ).json()["meta"]["total"]
    if tasks_total == 0:
        log("[5/6] 生成标注任务与审核记录")
        annotation_images = pick_images(api, admin, "benign", 5, used)
        used.update(item["id"] for item in annotation_images)

        def create_task(image_id):
            return api.call(
                "POST",
                "/annotation-tasks",
                admin,
                expect=201,
                json={"image_ids": [image_id], "priority": 1},
            )["task_ids"][0]

        first = create_task(annotation_images[0]["id"])
        draft_task = create_task(annotation_images[1]["id"])
        pending = [create_task(item["id"]) for item in annotation_images[2:]]
        api.call("POST", f"/annotation-tasks/{first}/claim", tokens["annotator"])
        image = annotation_images[0]
        annotation = api.call(
            "POST",
            "/annotations",
            tokens["annotator"],
            expect=201,
            json={"image_id": image["id"], "mask_rle": rle(image["width"], image["height"]), "source": "manual"},
        )
        api.call("POST", f"/annotations/{annotation['id']}/submit", tokens["annotator"])
        approved = api.call(
            "POST",
            f"/annotations/{annotation['id']}/reviews",
            tokens["reviewer"],
            json={"decision": "approve", "comment": "演示数据：复核通过"},
        )
        api.call("POST", f"/annotation-tasks/{draft_task}/claim", tokens["annotator"])
        draft_image = annotation_images[1]
        api.call(
            "POST",
            "/annotations",
            tokens["annotator"],
            expect=201,
            json={
                "image_id": draft_image["id"],
                "mask_rle": rle(draft_image["width"], draft_image["height"]),
                "source": "manual",
            },
        )
        log(
            f"      标注：approved={approved['status']}，草稿 1 条，待领取 {len(pending)} 条"
        )
    else:
        log(f"[5/6] 已有标注任务 {tasks_total} 条，跳过标注演示")

    marker = api.call("GET", "/patients", tokens["screener"], params={"q": "DEMO-P001"})
    if marker:
        log("[6/6] 已有筛查演示数据，跳过")
    else:
        log("[6/6] 生成筛查/报告演示数据并执行真实推理")
        selected = {
            "benign": pick_images(api, admin, "benign", 2, used),
            "malignant": pick_images(api, admin, "malignant", 2, used),
            "normal": pick_images(api, admin, "normal", 1, used),
        }
        images = [selected["benign"][0], selected["malignant"][0], selected["normal"][0]]
        templates = api.call("GET", "/report-templates", tokens["screener"])
        template = next(item for item in templates if item["active"])
        results, study_ids = {}, {}

        for index, image in enumerate(images, start=1):
            patient_no, study_no = f"DEMO-P{index:03d}", f"DEMO-US-{index:03d}"
            patient = api.call(
                "POST",
                "/patients",
                tokens["screener"],
                expect=201,
                json={
                    "patient_no": patient_no,
                    "gender": "F",
                    "birth_year": 1965 + index,
                    "remark": "演示数据",
                },
            )
            study = api.call(
                "POST",
                "/studies",
                tokens["screener"],
                expect=201,
                json={
                    "patient_id": patient["id"],
                    "study_no": study_no,
                    "study_date": date.today().isoformat(),
                    "indication": "乳腺超声筛查（演示）",
                    "image_ids": [image["id"]],
                },
            )
            task = api.call(
                "POST",
                "/screen-tasks",
                tokens["screener"],
                expect=201,
                json={"study_id": study["id"], "priority": 1},
            )
            api.call("POST", f"/screen-tasks/{task['id']}/claim", tokens["screener"])
            inference = api.call(
                "POST",
                "/inference-tasks",
                tokens["screener"],
                expect=202,
                headers={"Idempotency-Key": f"demo-inference-{study_no}"},
                json={"image_id": image["id"]},
            )
            finished = api.wait_inference(tokens["screener"], inference["task_id"])
            if finished["status"] != "succeeded":
                raise RuntimeError(f"{study_no} 推理失败：{finished.get('error')}")
            results[index] = finished["result"]
            study_ids[index] = study["id"]
            log(f"      {study_no} 推理完成：{finished['result']['elapsed_ms']}ms")

        def report(study_id, result, sign):
            created = api.call(
                "POST",
                "/reports",
                tokens["screener"],
                expect=201,
                json={
                    "study_id": study_id,
                    "template_id": template["id"],
                    "inference_result_id": result["id"],
                    "content": {
                        "findings": "科研样例：乳腺超声可见低回声区，边界尚清。",
                        "impression": "模型提示异常区域，已由医生复核。",
                        "recommendation": "建议结合临床及其他影像检查，由专业医师评估。",
                    },
                },
            )
            api.call("POST", f"/reports/{created['id']}/submit", tokens["screener"])
            if sign:
                api.call(
                    "POST",
                    f"/reports/{created['id']}/sign",
                    tokens["reviewer"],
                    json={"decision": "sign", "comment": "演示数据：审核签发"},
                )
            return created["id"]

        # 1：完整签发；2：提交待审核；3：完成推理待医生复核
        for index in (1, 2):
            api.call(
                "POST",
                f"/studies/{study_ids[index]}/reviews",
                tokens["screener"],
                json={"decision": "accept", "comment": "演示数据：医生复核通过"},
            )
        report(study_ids[1], results[1], sign=True)
        report(study_ids[2], results[2], sign=False)

        # 两条待领取任务，供工作列表展示
        for index in (4, 5):
            image = pick_images(api, admin, "benign", 1, used)[0]
            used.add(image["id"])
            patient = api.call(
                "POST",
                "/patients",
                tokens["screener"],
                expect=201,
                json={"patient_no": f"DEMO-P{index:03d}", "gender": "F", "birth_year": 1970 + index},
            )
            study = api.call(
                "POST",
                "/studies",
                tokens["screener"],
                expect=201,
                json={
                    "patient_id": patient["id"],
                    "study_no": f"DEMO-US-{index:03d}",
                    "study_date": date.today().isoformat(),
                    "image_ids": [image["id"]],
                },
            )
            api.call(
                "POST",
                "/screen-tasks",
                tokens["screener"],
                expect=201,
                json={"study_id": study["id"], "priority": 3},
            )
        log("      已生成：1 份已签发报告、1 份待审核报告、1 条待复核、2 条待领取筛查任务")

    # 额外补充“已处理/处理中”记录，让工作台包含完整状态
    for index, mode in ((6, "done"), (7, "in_progress")):
        patient_no = f"DEMO-P{index:03d}"
        if api.call("GET", "/patients", tokens["screener"], params={"q": patient_no}):
            continue
        label = "benign" if mode == "done" else "malignant"
        image = pick_images(api, admin, label, 1, used)[0]
        used.add(image["id"])
        patient = api.call(
            "POST",
            "/patients",
            tokens["screener"],
            expect=201,
            json={"patient_no": patient_no, "gender": "F", "birth_year": 1960 + index},
        )
        study = api.call(
            "POST",
            "/studies",
            tokens["screener"],
            expect=201,
            json={
                "patient_id": patient["id"],
                "study_no": f"DEMO-US-{index:03d}",
                "study_date": date.today().isoformat(),
                "indication": "乳腺超声筛查（演示）",
                "image_ids": [image["id"]],
            },
        )
        task = api.call(
            "POST",
            "/screen-tasks",
            tokens["screener"],
            expect=201,
            json={"study_id": study["id"], "priority": 2},
        )
        api.call("POST", f"/screen-tasks/{task['id']}/claim", tokens["screener"])
        inference = api.call(
            "POST",
            "/inference-tasks",
            tokens["screener"],
            expect=202,
            headers={"Idempotency-Key": f"demo-inference-DEMO-US-{index:03d}"},
            json={"image_id": image["id"]},
        )
        finished = api.wait_inference(tokens["screener"], inference["task_id"])
        if finished["status"] != "succeeded":
            raise RuntimeError(f"DEMO-US-{index:03d} 推理失败：{finished.get('error')}")
        if mode == "done":
            api.call(
                "POST",
                f"/studies/{study['id']}/reviews",
                tokens["screener"],
                json={"decision": "accept", "comment": "演示数据：复核完成"},
            )
        log(f"      DEMO-US-{index:03d} 已生成，状态 {mode}")

    overview = api.call("GET", "/stats/overview", admin)
    summary = {
        "images": overview["images"],
        "dataset_version": frozen.get("version"),
        "splits": frozen.get("counts"),
        "model_version": active["version"],
        "annotation_tasks": api.client.get(
            "/annotation-tasks", headers={"Authorization": "Bearer " + admin}, params={"page_size": 1}
        ).json()["meta"]["total"],
        "screen_tasks": overview["screen_tasks"],
        "reports": "1 signed + 1 pending_review",
    }
    log("PASS: 演示数据就绪")
    log(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint must surface failures
        log(f"FAIL: {exc}")
        sys.exit(1)
