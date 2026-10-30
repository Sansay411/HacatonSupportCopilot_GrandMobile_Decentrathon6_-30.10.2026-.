"""Запуск Sentra одной командой, без make (на Windows make обычно нет).

    python scripts/serve.py                 # рабочий режим: нужны data/rules.json и по возможности models/
    python scripts/serve.py --fixture       # явный режим на ТЕСТОВЫХ правилах из tests/fixtures (нет данных кейса)
    python scripts/serve.py --port 8001 --host 0.0.0.0

Режим --fixture копирует синтетические правила в var/fixture_data/ и запускает сервис с отдельной базой
var/fixture.db. Интерфейс при этом постоянно показывает, что правила тестовые и цитаты не относятся к Grand Mobile.
Никаких обращений он не создаёт: список пуст, пока их не добавят вручную или импортом.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--fixture", action="store_true", help="тестовые правила из tests/fixtures вместо data/rules.json")
    args = ap.parse_args()
    env = dict(os.environ)
    if args.fixture:
        d = ROOT / "var/fixture_data"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "tests/fixtures/rules_mini.json", d / "rules.json")
        env["COPILOT_DATA"] = str(d)
        env.setdefault("COPILOT_DB", str(ROOT / "var/fixture.db"))
        print("РЕЖИМ ТЕСТОВЫХ ПРАВИЛ: правила synthetic, номера пунктов не относятся к Grand Mobile.", file=sys.stderr)
    print(f"Sentra: http://{args.host}:{args.port}/  (база: {env.get('COPILOT_DB', ROOT / 'var/sentra.db')})", file=sys.stderr)
    return subprocess.call([sys.executable, "-m", "uvicorn", "copilot.api:app", "--host", args.host, "--port", str(args.port)],
                           cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
