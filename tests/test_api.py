import pytest

from conftest import HAS_DATA

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
    r = c.post("/triage?enqueue=true", json={"kind": "report", "messages": [{"role": "player", "text": "застрял"}]})
    qid = r.json()["queue_id"]
    assert c.post("/feedback", json={"queue_id": qid, "action": "send"}).json()["ok"]
