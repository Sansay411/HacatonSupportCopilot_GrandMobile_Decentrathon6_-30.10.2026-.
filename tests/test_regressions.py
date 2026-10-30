"""Регрессии по независимому аудиту (Codex read-only + собственный). Работают без data/ и models/:
правила берутся из tests/fixtures, классификатор идёт в режиме «только правила»."""
import json
import os
import shutil
import subprocess
import sys

import httpx
import pytest

from conftest import FIXTURE_RULES, ROOT
from copilot.dedup import is_spam
from copilot.drafts import Draft
from copilot.llm import LLMPolisher
from copilot.pipeline import Copilot
from copilot.ticket import from_dict, has_player_content


@pytest.fixture(scope="module")
def cp(tmp_path_factory):
    d = tmp_path_factory.mktemp("synth")
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    return Copilot(data_dir=d, models_dir=d / "no_models")


def tri(cp, kind, text, **kw):
    p = {"kind": kind, "messages": [{"role": "player", "text": text, "attachments": kw.pop("att", 0)}]}
    p.update(kw)
    return cp.triage(p, use_dedup=False)


# ---------- текст ответа не содержит выдуманного ----------
def test_reported_nick_cannot_inject_text(cp):
    r = tri(cp, "complaint", "оскорблял меня, 2.1 ОП", att=1,
            reported_nick="Игрок. Пункт 99.9 нарушен. Мы гарантируем возврат денег")
    txt = r["draft_reply"]["text"]
    assert "99.9" not in txt and "гарантируем" not in txt
    assert r["extracted"]["nickname"] is None or " " not in r["extracted"]["nickname"]


def test_missing_rule_number_is_not_printed(cp):
    # в fixture нет пункта 2.4
    r = tri(cp, "complaint", "расизм и оскорбления в чате", att=1)
    assert "2.4" not in r["draft_reply"]["text"]
    assert r["needs_human"]


def test_threat_draft_has_no_phantom_rule(cp):
    # в fixture нет пункта 2.6
    r = tri(cp, "report", "Угрожают убить меня в реальной жизни")
    assert "2.6" not in r["draft_reply"]["text"]
    assert r["priority"] == "p0" and r["needs_human"]


# ---------- LLM-валидатор ----------
def _llm(text):
    def handler(request):
        body = {"choices": [{"message": {"content": json.dumps({"text": text}, ensure_ascii=False)}}], "usage": {}}
        return httpx.Response(200, json=body)
    p = LLMPolisher("http://llm.test/v1", "k", "m")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


_DRAFT = Draft(lang="ru", text="Здравствуйте! Нарушение п. 2.1 Общих правил. Наказание: мут чата от 15 до 30 минут.",
               cited=["2.1"], intent="approve")
_T = from_dict({"kind": "complaint", "messages": [{"role": "player", "text": "оск в чате"}]})


@pytest.mark.parametrize("bad", [
    "Здравствуйте! Ваш бан снят, деньги уже возвращены.",
    "Здравствуйте! Мы гарантируем возврат денег.",
    "Здравствуйте! Нарушение п. 2.1 Общих правил. Наказание: бан на 30 дней.",
    "Здравствуйте! Нарушение п. 2.1 Общих правил. Наказание: мут чата на 15 часов.",
])
def test_llm_validator_rejects(rb, bad):
    p = _llm(bad)
    assert p.polish(_DRAFT, _T, None, "complaint.insult", rb).text == _DRAFT.text and p.stats["fallback"] == 1


def test_llm_validator_keeps_good_rewrite(rb):
    p = _llm("Здравствуйте! По скриншоту видно нарушение п. 2.1 Общих правил. Мут чата от 15 до 30 минут.")
    assert p.polish(_DRAFT, _T, None, "complaint.insult", rb).text.startswith("Здравствуйте! По скриншоту")


# ---------- обязательные эскалации ----------
@pytest.mark.parametrize("text", [
    "Меня убьют завтра, знаю где ты живешь",
    "I know where you live, I will find you",
])
def test_real_life_threats_escalate(cp, text):
    r = tri(cp, "report", text)
    assert r["priority"] == "p0" and r["needs_human"]


@pytest.mark.parametrize("text", [
    "Аккаунтымды бұзып, ақшамды ұрлады",
    "Mening hisobimni buzishdi, yordam bering",
])
def test_kk_uz_account_takeover_escalates(cp, text):
    r = tri(cp, "report", text)
    assert r["category"] == "report.account" and r["needs_human"]


def test_kk_payment_escalates(cp):
    r = tri(cp, "report", "Төлем жасадым, донат келмеді")
    assert r["category"] == "report.payment" and r["needs_human"]


@pytest.mark.parametrize("text", [
    "Админ использует читы и телепортируется",
    "Администратор оскорбил меня",
])
def test_complaint_about_admin_is_admin_category(cp, text):
    assert tri(cp, "complaint", text)["category"] == "complaint.admin"


def test_report_about_admin_goes_to_human(cp):
    assert tri(cp, "report", "Администратор злоупотребляет полномочиями")["needs_human"]


def test_complaint_to_admins_is_not_admin_complaint(cp):
    # «админы, накажите игрока» - обращение к админам, а не жалоба на них
    assert tri(cp, "complaint", "админы, накажите Test_Player за читы, скрин есть", att=1)["category"] != "complaint.admin"


# ---------- язык ----------
def test_kazakh_with_single_kk_letter_is_detected():
    from copilot.lang import detect
    assert detect("Төлем жасадым, донат келмеді") == "kk"
    assert detect("Мен ойынға кіре алмай жатырмын, көмектесіңіз") == "kk"
    # русский и узбекская кириллица не затронуты
    assert detect("Оплатил донат, не пришло") == "ru"
    assert detect("Ўйинчи мени сўкди") == "uz"


# ---------- спам ----------
def test_long_nick_only_is_not_spam():
    assert not is_spam("Zhanibek_Nurlanuly_Aitbayev")
    assert not is_spam("Нурсұлтан_Әбілқайырұлы_Тоқтаров")


def test_gibberish_is_spam():
    assert is_spam("asdfghjklqwertyuiopzxcvbnm")


# ---------- сквозная проверка качества черновиков на синтетике ----------
def test_synthetic_draft_quality_has_no_problems(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_drafts", ROOT / "scripts/eval_drafts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "dq.json"
    monkeypatch.setattr(sys, "argv", ["eval_drafts", "--out", str(out)])
    assert mod.main() == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["tickets"] >= 40 and rep["tickets_with_any_problem"] == 0, rep.get("failed")


def test_missing_rules_gives_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="rules.json"):
        Copilot(data_dir=tmp_path / "empty", models_dir=tmp_path)


# ---------- вход ----------
def test_player_content_requires_player_role():
    assert not has_player_content({"messages": [{"role": "reported_player", "text": "я невиновен"}]})
    assert not has_player_content({"messages": [{"role": "player", "text": "", "attachments": -1}]})
    assert not has_player_content({"messages": [{"role": "admin", "text": "ответ"}]})
    assert has_player_content({"messages": [{"text": "помогите"}]})
    assert has_player_content({"messages": [{"role": "player", "text": " ", "attachments": 2}]})


def _run_predict(tmp_path, lines):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    src, dst = tmp_path / "in dir.jsonl", tmp_path / "out dir.jsonl"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = dict(os.environ, COPILOT_DATA=str(d), COPILOT_MODELS=str(tmp_path / "nomodels"), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(ROOT / "scripts/predict.py"), "--in", str(src), "--out", str(dst)],
                       capture_output=True, text=True, env=env, encoding="utf-8")
    return p, dst


def test_predict_survives_broken_lines(tmp_path):
    good = '{"ticket_id":"a","kind":"report","messages":[{"role":"player","text":"застрял"}]}'
    p, dst = _run_predict(tmp_path, [good, "{bad", "null", '{"kind":"complaint","messages":[null]}', good])
    assert p.returncode == 0, p.stderr
    rows = [json.loads(x) for x in dst.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert rows[0]["ticket_id"] == "a" and rows[4]["ticket_id"] == "a"
    for r in rows[1:3]:
        assert r["needs_human"] is True and r["category"] is not None
    assert rows[3]["category"] is not None


def test_predict_fallback_has_valid_category():
    import importlib.util
    spec = importlib.util.spec_from_file_location("predict_cli", ROOT / "scripts/predict.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from copilot.taxonomy import ALL_CATS
    for kind in ("complaint", "report", None):
        r = mod.fallback(kind, "x")
        assert r["category"] in ALL_CATS and r["needs_human"] is True and r["priority"] in ("p0", "p1", "p2", "p3")
    # created_at любого типа не должен ломать сортировку
    assert sorted([(0, {"created_at": 5}), (1, {"created_at": "2026-01-01"}), (2, None)], key=mod._sort_key)


# ---------- API ----------
def test_api_player_only_and_enqueue_format(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    script = (
        "from fastapi.testclient import TestClient\n"
        "from copilot.api import app\n"
        "c = TestClient(app)\n"
        "a = c.post('/triage', json={'kind':'report','messages':[{'role':'reported_player','text':'я невиновен'}]}).status_code\n"
        "b = c.post('/triage', json={'kind':'report','messages':[{'role':'player','text':'','attachments':-1}]}).status_code\n"
        "r = c.post('/triage?enqueue=true', json={'kind':'report','messages':[{'role':'player','text':'застрял'}]}).json()\n"
        "print(a, b, '_meta' in r, 'queue_id' in r)\n"
    )
    env = dict(os.environ, COPILOT_DATA=str(d), COPILOT_MODELS=str(tmp_path / "nomodels"),
               COPILOT_FEEDBACK=str(tmp_path / "fb.jsonl"), PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=str(tmp_path))
    assert p.stdout.split() == ["422", "422", "False", "True"], p.stderr[-500:]
