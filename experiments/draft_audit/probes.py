"""Пробы вынесены в tests/fixtures/draft_probes.py, чтобы их использовали и тесты, и аудит."""
import sys

import common as C

sys.path.insert(0, str(C.ROOT / "tests" / "fixtures"))
from draft_probes import PROBES  # noqa: E402,F401
