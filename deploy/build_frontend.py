"""Build the Vue frontend and copy ``frontend/dist`` into ``deploy/html``.

The Docker Compose Nginx serves ``deploy/html`` as static files. This script
keeps the built assets out of Git while making the deployment entry explicit.

源文件内容未变化时自动复用 ``frontend/dist`` 与 ``deploy/html``，避免每次启动
都重新执行 Vite 构建；需要强制重建时使用 ``--force``。

Usage (repository root):
    python deploy/build_frontend.py
    python deploy/build_frontend.py --skip-install
    python deploy/build_frontend.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
TARGET = ROOT / "deploy" / "html"
STAMP = FRONTEND / ".vite-build-stamp"
TARGET_STAMP = TARGET / ".vite-build-stamp"

# 影响构建产物的源码与配置；package-lock 变化意味着依赖版本变化。
ENTRIES = (
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.node.json",
    "env.d.ts",
)
DIRECTORIES = ("src", "public")

# On Windows npm is npm.CMD; subprocess cannot resolve the bare name.
NPM = shutil.which("npm")


def run(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}  (cwd={cwd})")
    try:
        subprocess.run(command, cwd=str(cwd), check=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"command failed with exit code {exc.returncode}: {' '.join(command)}") from exc


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for name in DIRECTORIES:
        path = FRONTEND / name
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    for name in ENTRIES:
        path = FRONTEND / name
        if path.is_file():
            files.append(path)
    for path in sorted(files):
        digest.update(path.relative_to(FRONTEND).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read_stamp(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="skip npm ci")
    parser.add_argument("--force", action="store_true", help="force a fresh Vite build and copy")
    args = parser.parse_args()

    fingerprint = source_fingerprint()
    dist_ready = (DIST / "index.html").is_file() and read_stamp(STAMP) == fingerprint

    if args.force or not dist_ready:
        if not NPM:
            raise SystemExit("npm not found. Install Node.js 20+ and ensure npm is on PATH.")
        if not args.skip_install:
            run([NPM, "ci"], FRONTEND)
        run([NPM, "run", "build"], FRONTEND)
        if not DIST.is_dir():
            raise SystemExit(f"build output not found: {DIST}")
        STAMP.write_text(fingerprint, encoding="utf-8")
        print("frontend build finished")
    else:
        print("frontend sources unchanged; reusing frontend/dist")

    target_ready = (TARGET / "index.html").is_file() and read_stamp(TARGET_STAMP) == fingerprint
    if args.force or not target_ready:
        TARGET.mkdir(parents=True, exist_ok=True)
        for item in TARGET.iterdir():
            if item == TARGET_STAMP:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        shutil.copytree(DIST, TARGET, dirs_exist_ok=True)
        TARGET_STAMP.write_text(fingerprint, encoding="utf-8")
        print(f"copied {DIST} -> {TARGET}")
    else:
        print("deploy/html already up to date; skipped copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
