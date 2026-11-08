"""Cheap guards on the static UI (the browser walkthrough lives in scripts/ui_smoke.js)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_assets_are_served(client):
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200, path


def test_disclosure_and_demo_role_labels_are_in_the_page(client):
    html = client.get("/").text
    assert "Synthetic demo data. No real student records." in html
    assert "no messages are sent" in html
    assert "Demo role switch" in html and "Not access control" in html
    assert "Academic case desk" in html


def test_ui_never_uses_innerhtml_so_source_text_cannot_inject_markup():
    js = (STATIC / "app.js").read_text()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in js, banned


def test_ui_is_light_only_and_has_no_gradients():
    css = (STATIC / "style.css").read_text()
    assert "color-scheme: light" in css
    assert "prefers-color-scheme: dark" not in css
    assert "gradient" not in css.lower()
    assert "backdrop-filter" not in css


def test_misleading_score_label_is_gone():
    js = (STATIC / "app.js").read_text()
    assert "Apply score change" not in js
    assert "Record score recommendation" in js and "No Canvas change" in js


def test_upload_zone_accepts_documents_and_says_so():
    js = (STATIC / "app.js").read_text()
    assert "Drop a screenshot, PDF, or document" in js
    for needle in ("application/pdf", ".docx", ".csv", "/api/intake/upload"):
        assert needle in js, needle


def test_mobile_shell_rules_are_embedded_in_the_page_itself(client):
    html = client.get("/").text
    assert "<style>" in html and "@media (max-width: 768px)" in html
    for rule in (
        ".app {\n        display: flex !important;",
        "position: static !important;",
        "flex-direction: column !important;",
        ".menu-btn { display: inline-flex !important;",
    ):
        assert rule in html, rule
    assert "fonts.googleapis.com/css2?family=Inter" in html and "JetBrains+Mono" in html


def test_palette_has_no_beige_and_uses_the_dark_sidebar_and_blue_accent():
    css = (STATIC / "style.css").read_text().lower()
    for token in (
        "--sidebar-bg: #0f172a",
        "--brand: #1e40af",
        "--border: #e2e8f0",
        "--text: #0f172a",
        "--text-secondary: #475569",
        "--bg-subtle: #f8fafc",
    ):
        assert token in css, token
    for beige in ("#f5f4ef", "#ecebe2", "#fbf3df", "#fdf3e3", "#faf9f5"):
        assert beige not in css, beige
    assert "--shadow-sm:" in css and "box-shadow: var(--shadow-sm)" in css


def test_dashboard_is_the_landing_page_and_has_no_invented_figures():
    js = (STATIC / "app.js").read_text()
    assert "정보는 있는데, 사건은 없다" in js
    assert '|| "#/dashboard"' in js
    assert "time saved" not in js.lower()
    for label in ("Total cases", "Need action", "Closed today", "Avg model latency"):
        assert label in js


def test_guardrail_demo_is_labelled_as_not_from_a_model():
    js = (STATIC / "app.js").read_text()
    assert "/guardrail-demo" in js
    assert "did not come from a model" in (STATIC.parent / "service.py").read_text()


def test_spec_layout_pieces_exist_in_the_stylesheet():
    css = (STATIC / "style.css").read_text()
    for sel in (".pipeline", ".gtable", ".tlmark", ".step.active", ".movemenu", ".evpill", ".drop"):
        assert sel in css, sel
    assert "220px" in css and "1100px" in css
