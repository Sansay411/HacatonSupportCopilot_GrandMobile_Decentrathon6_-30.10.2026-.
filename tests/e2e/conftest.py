"""Фикстуры сквозных тестов: Playwright и браузер. Если браузера нет, тесты пропускаются с понятной причиной.

Выбор браузера: переменная SENTRA_E2E_BROWSER (msedge, chrome или chromium), по умолчанию перебираются все три.
Данные кейса на машине отсутствуют, поэтому сервер поднимается на синтетических правилах tests/fixtures без ML-моделей.
"""
import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    wanted = os.environ.get("SENTRA_E2E_BROWSER")
    tried = []
    for name in ([wanted] if wanted else ["msedge", "chrome", "chromium"]):
        try:
            kw = {} if name == "chromium" else {"channel": name}
            b = pw.chromium.launch(headless=True, **kw)
        except Exception as e:  # браузера нет: пробуем следующий
            tried.append(f"{name}: {str(e).splitlines()[0][:80]}")
            continue
        yield b
        b.close()
        return
    pytest.skip("нет браузера для Playwright (" + "; ".join(tried) + ")")


@pytest.fixture(scope="module")
def tmp_module(tmp_path_factory):
    return tmp_path_factory.mktemp("e2e")
