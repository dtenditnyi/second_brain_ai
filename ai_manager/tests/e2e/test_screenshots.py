"""Responsive screenshots + layout metrics for every page and width.

Not part of the normal run: executes only when SCREENSHOT_DIR is set, e.g.
    SCREENSHOT_DIR=../docs/audit/responsive/before ../venv/Scripts/python.exe -m pytest tests/e2e/test_screenshots.py
Writes <dir>/<page>_<width>.png and <dir>/metrics.json.
"""
import json
import os

import pytest

from tests.e2e.conftest import login
from tests.e2e.responsive_helpers import PAGES, WIDTHS, HEIGHT, seed, run_action, METRICS_JS

OUT = os.environ.get("SCREENSHOT_DIR")
pytestmark = [pytest.mark.responsive,
              pytest.mark.skipif(not OUT, reason="set SCREENSHOT_DIR to take screenshots")]


def test_capture_all(browser, live_server, e2e_user, e2e_admin, isolated_vault):
    seed(e2e_user, isolated_vault)
    os.makedirs(OUT, exist_ok=True)
    metrics = {}
    contexts = {}
    for role, name in (("user", "e2e"), ("admin", "e2eroot")):
        ctx = browser.new_context()
        pg = ctx.new_page()
        login(pg, live_server, name)
        contexts[role] = ctx
    contexts[None] = browser.new_context()
    for page_name, (path, role, action) in PAGES.items():
        for w in WIDTHS:
            pg = contexts[role].new_page()
            pg.set_viewport_size({"width": w, "height": HEIGHT[w]})
            pg.goto(f"{live_server.url}{path}")
            pg.wait_for_load_state("networkidle")
            if action:
                run_action(pg, action)
            pg.wait_for_timeout(1200)  # sidebar progress bar transition
            pg.screenshot(path=os.path.join(OUT, f"{page_name}_{w}.png"), full_page=False)
            metrics[f"{page_name}_{w}"] = pg.evaluate(METRICS_JS)
            pg.close()
    with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=1)
    for ctx in contexts.values():
        ctx.close()
