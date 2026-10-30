"""Раздача интерфейса Sentra и бренд-ассетов. Работает на синтетических правилах, без data/ и models/."""
import xml.etree.ElementTree as ET

from support import ROOT


def test_index_and_static_assets(boot):
    c, _ = boot()
    page = c.get("/")
    assert page.status_code == 200 and "Sentra" in page.text
    for url in ("/static/sentra.css", "/static/core.js", "/static/viz.js", "/static/views.js", "/static/queue.js",
                "/static/app.js", "/static/assets/sentra-mark.svg"):
        assert c.get(url).status_code == 200, url
    icon = c.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg+xml")


def test_ui_has_no_demo_queue_and_no_fake_send():
    js = "\n".join((ROOT / "admin_ui" / f).read_text(encoding="utf-8")
                   for f in ("core.js", "viz.js", "views.js", "queue.js", "app.js"))
    html = (ROOT / "admin_ui/index.html").read_text(encoding="utf-8")
    for needle in ("loadDemo", "data-demo", "демо-очеред", "Отправлено игроку", "Сервис в норме", "Отправить с правкой"):
        assert needle not in js and needle not in html, needle
    assert "navigator.clipboard" in js and "Idempotency-Key" in js and "expected_rev" in js


def test_brand_assets_are_valid_svg():
    assets = sorted((ROOT / "admin_ui/assets").glob("*.svg"))
    assert {p.name for p in assets} >= {"sentra-mark.svg", "sentra-wordmark.svg", "sentra-lockup.svg", "favicon.svg"}
    for p in assets:
        root = ET.parse(p).getroot()
        assert root.tag.endswith("svg") and root.get("viewBox"), p.name
