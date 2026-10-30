"""Общие константы тестов. Лежат отдельно от conftest.py: в tests/ и tests/e2e/ два conftest.py, и импорт по имени
`conftest` в полном прогоне попадал бы не в тот файл."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_RULES = ROOT / "tests/fixtures/rules_mini.json"
HAS_DATA = (ROOT / "data/rules.json").exists() and (ROOT / "models/category.pkl").exists()
