"""Сквозной тест на реальных data/ и models/: выполняется только когда выдача кейса и модели лежат на месте."""
import pytest

from support import HAS_DATA

pytestmark = pytest.mark.skipif(not HAS_DATA, reason="нет data/ и models/")


def test_triage_endpoint():
    from fastapi.testclient import TestClient
    from copilot.api import app
    c = TestClient(app)
    r = c.post("/triage", json={"kind": "complaint", "messages": [
        {"role": "player", "text": "Arman_Petrov оскорблял меня в чате, 2.1 ОП", "attachments": 2}]})
    assert r.status_code == 200
    body = r.json()
    assert "_meta" not in body and body["draft_reply"]["cited"]
    assert c.post("/triage", json={"kind": "report", "messages": [{"role": "player", "text": " "}]}).status_code == 422
    assert c.post("/triage", json={"kind": "other", "messages": []}).status_code == 422
    t = c.post("/tickets", json={"kind": "report", "text": "застрял", "reporter": "real-1"}).json()["ticket"]
    done = c.post(f"/tickets/{t['id']}/decision", json={"action": "close", "expected_rev": t["rev"], "reason": "no_action"})
    assert done.status_code == 200 and done.json()["status"] == "closed"
