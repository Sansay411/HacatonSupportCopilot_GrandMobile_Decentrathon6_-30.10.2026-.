"""Запуск настоящего Sentra для записи демо-видео на ИЗОЛИРОВАННОЙ базе.

Что настоящее: правила и модели из data/ и models/ (только чтение), пайплайн, проверка текста, хранилище SQLite.
Что изолировано: база demo_video/work/demo.db (production-база var/sentra.db не затрагивается), сводка шаблонов
подменена синтетической, чтобы формулировки ответов админов из выдачи не попали в кадр. LLM выключена,
внешние запросы с текстами обращений не отправляются.

    python demo_video/scripts/start_server.py [--port 8765] [--fresh]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "demo_video" / "work"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fresh", action="store_true", help="удалить демо-базу перед стартом")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    db = WORK / "demo.db"
    if args.fresh:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", COPILOT_DB=str(db),
               COPILOT_TEMPLATES=str(ROOT / "tests/fixtures/template_summary_synthetic.json"),
               COPILOT_TEMPLATES_PRIVATE=str(WORK / "нет_приватных_шаблонов.json"))
    for k in ("COPILOT_LLM_BASE_URL", "COPILOT_LLM_API_KEY", "COPILOT_LLM_MODEL", "COPILOT_DATA", "COPILOT_MODELS"):
        env.pop(k, None)
    print(f"Sentra (демо-запись): http://127.0.0.1:{args.port}/  база: {db.name}", file=sys.stderr)
    return subprocess.call([sys.executable, "-m", "uvicorn", "copilot.api:app", "--host", "127.0.0.1",
                            "--port", str(args.port)], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
