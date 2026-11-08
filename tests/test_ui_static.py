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
    assert "Drop screenshot, PDF, or document" in js
    for needle in ("application/pdf", ".docx", ".csv", "/api/intake/upload"):
        assert needle in js, needle
