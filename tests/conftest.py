import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_RULES = ROOT / "tests/fixtures/rules_mini.json"
HAS_DATA = (ROOT / "data/rules.json").exists() and (ROOT / "models/category.pkl").exists()


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
