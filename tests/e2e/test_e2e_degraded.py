"""Деградированные режимы в настоящем браузере: нет rules.json, повреждена база. Интерфейс обязан сказать правду."""
import pytest
from playwright.sync_api import expect

from e2e_helpers import Page, Server

pytestmark = pytest.mark.e2e


def test_without_rules_the_ui_shows_exact_diagnostics_and_refuses_triage(browser, tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("norules"), rules=False).start()
    pg = Page(browser, srv.url)
    try:
        p = pg.page
        p.goto("/")
        expect(p.locator("#view")).to_contain_text("Триаж недоступен")
        expect(p.locator("#view")).to_contain_text("rules.json")
        expect(p.locator("#live")).to_contain_text("Триаж недоступен")
        expect(p.locator("#live")).not_to_contain_text("в норме")
        expect(p.locator("#view")).not_to_contain_text("Сервис в норме")
        assert srv.get("/health")["ready"] is False
        status, body = srv.post("/triage", {"kind": "report", "messages": [{"role": "player", "text": "застрял"}]})
        assert status == 503 and body["detail"]["code"] == "triage_unavailable"
        # форма не подменяет результат: ошибка сервера показана в диалоге, обращение не создано
        p.click("#new-btn")
        p.fill("#in-text", "оскорблял меня")
        p.click("#in-go")
        expect(p.locator("#in-err")).to_contain_text("Триаж недоступен")
        p.click("#in-cancel")
        assert srv.get("/tickets")["total"] == 0
        # диагностика называет недостающие файлы
        p.goto("/#/quality")
        p.reload()
        expect(p.locator("#view")).to_contain_text("data/rules.json")
        expect(p.locator("#view")).to_contain_text("models/category.pkl")
        assert pg.errors == [], pg.errors
        assert set(pg.http_noise) <= {"503"}
    finally:
        pg.close()
        srv.stop()


def test_corrupted_database_is_reported_in_the_ui(browser, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("brokendb")
    (tmp / "broken.db").write_bytes(b"not a sqlite database " * 300)
    srv = Server(tmp, db="broken.db").start()
    pg = Page(browser, srv.url)
    try:
        p = pg.page
        p.goto("/#/quality")
        expect(p.locator("#view")).to_contain_text("повреждена")
        expect(p.locator("#banner")).to_be_visible()
        expect(p.locator("#live")).to_contain_text("Триаж недоступен")
        # контракт кейса не зависит от базы
        status, body = srv.post("/triage", {"kind": "report", "messages": [{"role": "player", "text": "застрял"}]})
        assert status == 200 and body["category"].startswith("report.")
        assert pg.errors == [], pg.errors
    finally:
        pg.close()
        srv.stop()
