"""Minimal browser smoke for the deployed UI; run after `docker compose up`.

Usage: python backend/scripts/e2e_ui.py [base_url]
Requires: pip install playwright && python -m playwright install chromium
"""

import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("UI_URL", "http://localhost:8080")).rstrip("/")
USERNAME = os.environ.get("DEMO_USERNAME", "admin")
PASSWORD = os.environ.get("DEMO_PASSWORD", "DemoPassword!123")

PAGES = [
    ("/dashboard", "总览"),
    ("/data/images", "影像检索"),
    ("/data/datasets", "数据集版本"),
    ("/models", "模型与指标"),
    ("/stats", "统计看板"),
    ("/admin/report-templates", "报告模板"),
    ("/admin/audit", "审计日志"),
]


def main():
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(BASE + "/login")
        page.fill("input[placeholder*='用户名'], input[placeholder*='账号']", USERNAME)
        page.fill("input[type='password']", PASSWORD)
        page.click("button[type='submit']")
        page.wait_for_url(re.compile(r".*/dashboard.*"), timeout=30000)
        print("PASS login")
        for path, label in PAGES:
            page.goto(BASE + path)
            page.wait_for_selector(f"text={label}", timeout=20000)
            print(f"PASS {path}")
        browser.close()
    if errors:
        print("PAGE ERRORS:", errors)
        raise SystemExit(1)
    print("UI SMOKE PASSED")


if __name__ == "__main__":
    main()
