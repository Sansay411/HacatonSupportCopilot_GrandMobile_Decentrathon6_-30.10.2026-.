"""Интерфейс Sentra: раздача статики, /metrics, демо-флаг. Работает на синтетических правилах, без data/ и models/."""
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from conftest import FIXTURE_RULES, ROOT


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE_RULES, data / "rules.json")
    monkeypatch.setenv("COPILOT_DATA", str(data))
    monkeypatch.setenv("COPILOT_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("COPILOT_FEEDBACK", str(tmp_path / "feedback.jsonl"))
    sys.modules.pop("copilot.api", None)  # модуль читает окружение при импорте
    from fastapi.testclient import TestClient
    import copilot.api as api
    yield TestClient(api.app), api
    sys.modules.pop("copilot.api", None)


def test_index_and_static_assets(client):
    c, _ = client
    page = c.get("/")
    assert page.status_code == 200 and "Sentra" in page.text
    for url in ("/static/sentra.css", "/static/app.js", "/static/assets/sentra-mark.svg"):
        assert c.get(url).status_code == 200, url
    icon = c.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg+xml")


def test_health_marks_synthetic_rules_as_demo(client):
    c, _ = client
    body = c.get("/health").json()
    assert body["demo"] is True and body["rules"] > 0


def test_metrics_endpoint(client, tmp_path):
    c, api = client
    body = c.get("/metrics").json()
    assert body["available"] is True and "category_accuracy" in body
    api.METRICS_JSON = tmp_path / "нет.json"
    assert c.get("/metrics").json()["available"] is False


def test_repeat_complaint_is_flagged_as_duplicate(client):
    """Демо-очередь опирается на это: повтор от того же заявителя на того же нарушителя помечается дублем."""
    c, _ = client

    def send(text):
        return c.post("/triage?enqueue=true", json={
            "kind": "complaint", "reporter_hash": "r-1", "reported_nick": "Test_Player",
            "messages": [{"role": "player", "text": text, "attachments": 1}]}).json()

    assert send("Test_Player оскорблял меня и мою семью, скрин есть, 2.1 ОП")["is_spam_or_duplicate"] is False
    assert send("Test_Player снова оскорбляет мою семью")["is_spam_or_duplicate"] is True
    queue = c.get("/queue").json()
    assert len(queue) == 2 and all(q["request"]["reporter_hash"] == "r-1" for q in queue)


def test_brand_assets_are_valid_svg():
    assets = sorted((ROOT / "admin_ui/assets").glob("*.svg"))
    assert {p.name for p in assets} >= {"sentra-mark.svg", "sentra-wordmark.svg", "sentra-lockup.svg", "favicon.svg"}
    for p in assets:
        root = ET.parse(p).getroot()
        assert root.tag.endswith("svg") and root.get("viewBox"), p.name
