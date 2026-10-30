import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURE_RULES, HAS_DATA, ROOT  # noqa: E402,F401

# тесты не должны писать в рабочую базу var/sentra.db: по умолчанию база во временной папке
os.environ.setdefault("COPILOT_DB", str(Path(tempfile.mkdtemp(prefix="sentra-test-")) / "sentra.db"))


@pytest.fixture(scope="session")
def rb():
    from copilot.rules import load
    return load(str(FIXTURE_RULES))


@pytest.fixture(scope="session")
def copilot_full():
    if not HAS_DATA:
        pytest.skip("нет data/ и models/: тесты на реальных правилах пропущены")
    from copilot.pipeline import Copilot
    return Copilot()


@pytest.fixture()
def boot(tmp_path, monkeypatch):
    """Фабрика приложения: поднимает copilot.api заново с чистым окружением. Повторный вызов с тем же db_name
    имитирует перезапуск сервера: база та же, память процесса новая."""
    import shutil
    started = []

    def _boot(*, rules: bool = True, db_name: str = "sentra.db", data_name: str = "data", metrics: bool = False):
        from fastapi.testclient import TestClient
        data = tmp_path / data_name
        data.mkdir(exist_ok=True)
        if rules:
            shutil.copy(FIXTURE_RULES, data / "rules.json")
        monkeypatch.setenv("COPILOT_DATA", str(data))
        monkeypatch.setenv("COPILOT_MODELS", str(tmp_path / "no_models"))
        monkeypatch.setenv("COPILOT_DB", str(tmp_path / db_name))
        monkeypatch.setenv("COPILOT_METRICS", str(ROOT / "reports/metrics.json") if metrics else str(tmp_path / "нет.json"))
        monkeypatch.setenv("COPILOT_TEMPLATES_PRIVATE", str(tmp_path / "нет-private.json"))
        for k in ("COPILOT_LLM_BASE_URL", "COPILOT_LLM_API_KEY", "COPILOT_LLM_MODEL"):
            monkeypatch.delenv(k, raising=False)
        for old in started:      # прежний процесс «остановлен»
            if old.STORE is not None:
                old.STORE.close()
        sys.modules.pop("copilot.api", None)
        import copilot.api as api
        started.append(api)
        return TestClient(api.app), api

    yield _boot
    for api in started:
        if api.STORE is not None:
            api.STORE.close()
    sys.modules.pop("copilot.api", None)
