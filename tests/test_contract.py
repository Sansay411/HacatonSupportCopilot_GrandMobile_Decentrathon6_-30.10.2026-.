"""Контракт кейса: формат ответа make predict и POST /triage, которого нельзя ломать, и проверка пункта в тексте черновика."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from support import FIXTURE_RULES, ROOT
from copilot import drafts, taxonomy
from copilot.pipeline import Copilot
from copilot.rules import load

LANGS = {"ru", "uz", "kk", "en", "es", "pt", "und"}
TOP = {"lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human", "confidence", "reasons"}


def _tickets():
    rows = json.loads((ROOT / "tests/fixtures/synthetic_tickets.json").read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(rows):
        out.append({"ticket_id": f"C-{i:03d}", "kind": r["kind"], "created_at": f"2026-10-30T10:{i // 60:02d}:{i % 60:02d}Z",
                    "reporter_hash": f"rep-{i}", "messages": [{"role": "player", "text": r["text"], "attachments": r.get("att", 0)}]})
    return out


def _check_response(r, rb, kind):
    assert TOP <= set(r), set(r) ^ TOP
    assert set(r["extracted"]) == {"nickname", "rule_refs", "has_evidence", "server"}
    assert set(r["draft_reply"]) == {"lang", "text", "cited"}
    assert r["category"] in taxonomy.ALL_CATS and r["category"].split(".")[0] == kind
    assert r["priority"] in taxonomy.PRIORITIES and r["lang"] in LANGS and r["draft_reply"]["lang"] in LANGS
    assert isinstance(r["needs_human"], bool) and isinstance(r["is_spam_or_duplicate"], bool)
    assert 0.0 <= r["confidence"] <= 1.0 and all(isinstance(x, str) for x in r["reasons"])
    assert all(rb.exists(c) for c in r["draft_reply"]["cited"]), r["draft_reply"]["cited"]
    assert all(rb.exists(c) for c in r["extracted"]["rule_refs"])
    assert not [k for k in r if k.startswith("_")]


def test_predict_cli_output_matches_contract(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE_RULES, data / "rules.json")
    rows = _tickets()
    src, dst = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    lines.insert(3, "{битая строка")
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = dict(os.environ, COPILOT_DATA=str(data), COPILOT_MODELS=str(tmp_path / "нет"), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(ROOT / "scripts/predict.py"), "--in", str(src), "--out", str(dst)],
                       capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    out = [json.loads(x) for x in dst.read_text(encoding="utf-8").splitlines()]
    assert len(out) == len(lines)                                       # на каждую строку входа ровно один ответ
    rb = load(str(FIXTURE_RULES))
    ids = [o.get("ticket_id") for o in out]
    assert ids[:3] == ["C-000", "C-001", "C-002"] and ids[4] == "C-003"      # порядок входа сохранён, битая строка на своём месте
    assert out[3]["needs_human"] is True and out[3]["reasons"]
    for o, row in zip(out[:3] + out[4:], rows):
        _check_response({k: v for k, v in o.items() if k != "ticket_id"}, rb, row["kind"])


def test_triage_output_is_deterministic_per_input():
    d = FIXTURE_RULES.parent
    cp = Copilot(data_dir=_with_rules(d), models_dir=d / "нет")
    payload = {"kind": "complaint", "messages": [{"role": "player", "text": "Arman_Petrov оскорблял меня, 2.1 ОП", "attachments": 1}]}
    a = cp.triage(dict(payload), use_dedup=False)
    b = cp.triage(dict(payload), use_dedup=False)
    for r in (a, b):
        r["_meta"].pop("latency_ms", None)
    assert a == b


_RULES_DIRS = {}


def _with_rules(_):
    import tempfile
    from pathlib import Path
    if "d" not in _RULES_DIRS:
        d = Path(tempfile.mkdtemp(prefix="sentra-rules-"))
        shutil.copy(FIXTURE_RULES, d / "rules.json")
        _RULES_DIRS["d"] = d
    return _RULES_DIRS["d"]


# ---------------------------------------------------------------- номер пункта прямо в тексте черновика
def _phantom_draft(text, cited):
    def build(*a, **k):
        return drafts.Draft(lang="ru", text=text, cited=list(cited), intent="approve", auto_ok=True)
    return build


@pytest.fixture()
def cp(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    return Copilot(data_dir=d, models_dir=tmp_path / "нет")


def _triage(cp):
    return cp.triage({"kind": "complaint", "messages": [{"role": "player", "text": "Test_X оскорбил меня", "attachments": 1}]},
                     use_dedup=False)


def test_phantom_rule_number_in_draft_text_goes_to_human(cp, monkeypatch):
    monkeypatch.setattr(drafts, "build", _phantom_draft("Здравствуйте! Нарушение п. 99.9 Общих правил.", ["2.1"]))
    r = _triage(cp)
    assert r["needs_human"] is True
    assert any("в тексте черновика пункт" in x and "отсутствует в rules.json" in x for x in r["reasons"])


def test_rule_number_outside_confirmed_citations_goes_to_human(cp, monkeypatch):
    # пункт 3.1 существует, но подтверждённая цитата только 2.1: подмена цитаты текстом не проходит
    monkeypatch.setattr(drafts, "build", _phantom_draft("Здравствуйте! Нарушение п. 3.1 Общих правил.", ["2.1"]))
    r = _triage(cp)
    assert r["needs_human"] is True and any("не входит в подтверждённые цитаты" in x for x in r["reasons"])


def test_matching_rule_number_adds_no_reason(cp, monkeypatch):
    monkeypatch.setattr(drafts, "build", _phantom_draft("Здравствуйте! Нарушение п. 2.1 Общих правил (оскорбление).", ["2.1"]))
    r = _triage(cp)
    assert not any("в тексте черновика пункт" in x for x in r["reasons"])
