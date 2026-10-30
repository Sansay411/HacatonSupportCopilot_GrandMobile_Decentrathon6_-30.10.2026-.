"""Бонус «кандидаты в шаблоны»: тесты на синтетике, данные кейса не нужны."""
import json
import random

import pytest

from copilot import template_suggest as ts
from copilot.template_suggest import Params


# ---------------------------------------------------------------- нормализация
def test_normalize_replaces_nicks_ids_and_numbers():
    raw = "Уважаемый Vadim_Martin36, жалоба ##<digits> рассмотрена. Мут на 20 минут за 2.1 ОП"
    out = ts.normalize_reply(raw)
    assert "Vadim_Martin36" not in out and "{nick}" in out
    assert "{id}" in out and "{n} минут" in out
    assert "2.1 ОП" in out          # номер пункта сохраняется для проверки по rules.json


def test_reply_key_ignores_case_and_trailing_punctuation():
    assert ts.reply_key("Нажмите кнопку эвакуатора.") == ts.reply_key("нажмите кнопку  эвакуатора!!")


def test_reply_core_strips_greeting_and_signoff():
    core = ts.reply_core("Приветствую, {nick}. Нажмите кнопку эвакуатора в меню. С уважением, администрация Grand Mobile.")
    assert "эвакуатор" in core and "приветствую" not in core.lower() and "уважением" not in core.lower()
    assert len(ts.reply_core("Приветствую, одобрено.").split()) <= 1


# ---------------------------------------------------------------- ссылки на пункты
def test_verify_refs_uses_rules(rb):
    ok, bad = ts.verify_refs("Нарушение п. 2.1 ОП подтверждено", rb)
    assert ok == ["2.1"] and bad == []
    ok, bad = ts.verify_refs("Нарушение 9.9 ОП подтверждено", rb)
    assert ok == [] and bad


def test_player_text_for_clustering_drops_nicks_and_urls():
    t = ts.player_text_for_clustering("Arman_Petrov застрял <url> машина")
    assert "arman" not in t and "url" not in t and "застрял" in t


# ---------------------------------------------------------------- кластеризация
def test_clustering_separates_distinct_topics():
    rng = random.Random(1)
    a = [f"машина застряла в текстурах помогите вытащить {rng.randint(1, 99)}" for _ in range(60)]
    b = [f"оскорбил меня и семью в чате жалоба {rng.randint(1, 99)}" for _ in range(60)]
    labels, dist = ts.cluster_texts(a + b, 2)
    assert len(set(labels[:60])) == 1 and len(set(labels[60:])) == 1
    assert labels[0] != labels[-1] and len(dist) == 120


def test_clustering_tiny_input_does_not_crash():
    labels, _ = ts.cluster_texts(["один"], 3)
    assert list(labels) == [0]


# ---------------------------------------------------------------- сквозной сценарий
def _words(rng, n=6):
    return " ".join("".join(rng.choice("абвгдежзиклмнопрстуфхцчшэюя") for _ in range(rng.randint(4, 9))) for _ in range(n))


SYN = dict(min_cluster=20, per_cluster=80, max_k=3, min_lift=2.0, min_reply_count=5)


def _records():
    rng = random.Random(3)
    recs = []
    # кластер A: однотипный информативный ответ, наш сценарий общий -> кандидат
    for i in range(80):
        recs.append({"category": "report.help", "kind": "report", "ticket_id": f"a{i}", "lang": "ru",
                     "player_text": f"тачка застряла в текстурах у дома {rng.randint(1, 50)} помогите",
                     "reply": f"Приветствую, Ivan_Petrov{i}. Телепорт на МП закрыт, воспользуйтесь п. 3.1 ОП. С уважением, администрация.",
                     "intent": "help_generic", "draft": "Нужна помощь администратора в игре."})
    # кластер B: ответы разные, повторов нет
    for i in range(80):
        recs.append({"category": "report.help", "kind": "report", "ticket_id": f"b{i}", "lang": "ru",
                     "player_text": f"куда пропали мои деньги после обновления вопрос {rng.randint(1, 50)}",
                     "reply": _words(rng),
                     "intent": "question_unknown", "draft": "Уточните вопрос."})
    # кластер C: повторяется, но ссылка на несуществующий пункт
    for i in range(60):
        recs.append({"category": "report.rule", "kind": "report", "ticket_id": f"c{i}", "lang": "ru",
                     "player_text": f"читерит аимбот стреляет сквозь стены {rng.randint(1, 50)}",
                     "reply": "Нарушение по п. 9.9 ОП подтверждено, спасибо за обращение",
                     "intent": "need_evidence", "draft": "Нужны доказательства."})
    # кластер D: повторяется, и наш сценарий его уже покрывает
    for i in range(60):
        recs.append({"category": "report.vehicle", "kind": "report", "ticket_id": f"d{i}", "lang": "ru",
                     "player_text": f"упал в воду на машине что делать {rng.randint(1, 50)}",
                     "reply": "Нажмите кнопку эвакуатора в меню автомобиля, она вернёт машину",
                     "intent": "help_vehicle", "draft": "Нажмите кнопку эвакуатора в меню автомобиля, она вернёт машину."})
    return recs


def _stock_records():
    """Отписка «слежу за вами» стоит почти на каждом репорте: кластерам она не принадлежит."""
    rng = random.Random(5)
    recs = []
    for i in range(300):
        recs.append({"category": "report.offtopic", "kind": "report", "ticket_id": f"s{i}", "lang": "ru",
                     "player_text": f"просто пишу в репорт {rng.random()} {rng.choice(['привет', 'скучно', 'играем'])}",
                     "reply": "Приветствую, слежу за вами.", "intent": "clarify", "draft": "Уточните вопрос."})
    return recs


def test_stock_reply_is_not_a_candidate(rb):
    P = Params(**dict(SYN, per_cluster=100, max_k=2, stock_share=0.2, stock_min_count=50))
    recs = _stock_records() + _records()
    stock = ts.stock_replies(recs, P)
    assert stock and "слежу за вами" in stock[0]["template"].lower()
    out = ts.build_suggestions(recs, rb, P)
    assert not any(c["gap"] for c in out if c["category"] == "report.offtopic")
    assert any(c["gap"] for c in out if c["category"] == "report.help")


@pytest.fixture(scope="module")
def clusters(rb):
    P = Params(**SYN)
    return ts.build_suggestions(_records(), rb, P)


def _by(clusters, cat):
    return [c for c in clusters if c["category"] == cat]


def test_repeated_uncovered_cluster_becomes_candidate(clusters):
    cand = [c for c in _by(clusters, "report.help") if c["gap"]]
    assert cand, "кластер с повторяющимся ответом и общим сценарием должен быть кандидатом"
    c = cand[0]
    t = c["best"]
    assert "{nick}" in t["template"] and "Ivan_Petrov" not in t["template"]
    assert t["refs"] == ["3.1"] and t["unverified_refs"] == []
    assert c["top_reply_share"] > 0.9 and c["status"] == "кандидат в шаблон"


def test_diverse_replies_are_not_candidates(clusters):
    diverse = [c for c in _by(clusters, "report.help") if c["intent"] == "question_unknown"]
    assert diverse and not any(c["gap"] for c in diverse)
    assert all(c["status"] == "ответы не повторяются" for c in diverse)


def test_template_with_unknown_rule_is_rejected(clusters):
    c = _by(clusters, "report.rule")[0]
    assert not c["gap"] and "нет в rules.json" in c["status"]


def test_template_with_promise_is_rejected(rb):
    rng = random.Random(9)
    recs = [{"category": "complaint.admin", "kind": "report", "ticket_id": f"p{i}", "lang": "ru",
             "player_text": f"админ выдал бан зря верните {rng.randint(1, 99)} разбаньте",
             "reply": "Приветствую, наказание будет снято.", "intent": "help_generic", "draft": "Нужна помощь."}
            for i in range(60)]
    out = ts.build_suggestions(recs + _records() * 3, rb, Params(**SYN))   # фон нужен, чтобы ответ был «характерным»
    mine = [c for c in out if c["category"] == "complaint.admin"]
    assert mine and not any(c["gap"] for c in mine)
    assert "обещание" in mine[0]["status"]


def test_covered_cluster_is_not_candidate(clusters):
    c = _by(clusters, "report.vehicle")[0]
    assert not c["gap"] and c["status"] == "покрыт текущими сценариями"
    assert c["draft_sim"] > 0.9


def test_every_candidate_cites_only_existing_rules(clusters, rb):
    for c in clusters:
        if c["gap"]:
            assert all(rb.exists(r) for r in c["best"]["refs"])
            assert not c["best"]["unverified_refs"]


# ---------------------------------------------------------------- публичная сводка
def test_public_view_has_no_player_text(clusters):
    summary = ts.public_view(clusters, Params(**SYN), {"tickets": 280})
    blob = json.dumps(summary, ensure_ascii=False)
    for secret in ("тачка застряла", "куда пропали", "читерит аимбот", "Ivan_Petrov", "player_text", "ticket_id"):
        assert secret not in blob
    assert not any("examples" in c for c in summary["clusters"])
    assert summary["totals"]["candidates"] == sum(1 for c in clusters if c["gap"]) >= 1
    md = ts.render_markdown(summary)
    assert "Телепорт на МП закрыт" in md and "тачка застряла" not in md and "Ivan_Petrov" not in md
    assert "—" not in md and "–" not in md          # без тире в документации


def test_private_view_keeps_examples(clusters):
    c = _by(clusters, "report.help")[0]
    assert 0 < len(c["examples"]) <= 5 and c["examples"][0]["player_text"]


# ---------------------------------------------------------------- API
def test_templates_endpoint_without_summary(tmp_path, monkeypatch):
    from conftest import HAS_DATA
    if not HAS_DATA:
        pytest.skip("нет data/ и models/")
    from fastapi.testclient import TestClient
    from copilot import api
    monkeypatch.setattr(api, "TEMPLATES_JSON", tmp_path / "none.json")
    r = TestClient(api.app).get("/templates")
    assert r.status_code == 200 and r.json()["available"] is False


def test_templates_endpoint_with_summary(tmp_path, monkeypatch, clusters):
    from conftest import HAS_DATA
    if not HAS_DATA:
        pytest.skip("нет data/ и models/")
    from fastapi.testclient import TestClient
    from copilot import api
    summary = ts.public_view(clusters, Params(**SYN), {"tickets": 280})
    p = tmp_path / "s.json"
    p.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    p.with_suffix(".md").write_text(ts.render_markdown(summary), encoding="utf-8")
    monkeypatch.setattr(api, "TEMPLATES_JSON", p)
    monkeypatch.setattr(api, "TEMPLATES_MD", p.with_suffix(".md"))
    c = TestClient(api.app)
    body = c.get("/templates").json()
    assert body["available"] and body["clusters"] and all(x["gap"] for x in body["clusters"])
    assert "markdown" in body and len(c.get("/templates?only_candidates=false").json()["clusters"]) == len(summary["clusters"])
