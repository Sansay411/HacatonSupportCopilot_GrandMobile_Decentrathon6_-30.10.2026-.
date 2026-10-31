"""Остановить демо-сервер на порту 8765 и поднять заново на чистой демо-базе (production-база var/sentra.db не трогается).

    python demo_video/scripts/reset_server.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8765


def listener_pid() -> int | None:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if re.search(rf":{PORT}\s+\S+\s+LISTENING\s+(\d+)", line):
            return int(line.split()[-1])
    return None


def main() -> int:
    pid = listener_pid()
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        time.sleep(1.5)
    log = open(ROOT / "demo_video/work/server.log", "wb")
    flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: сервер переживает этот скрипт
    subprocess.Popen([sys.executable, str(ROOT / "demo_video/scripts/start_server.py"), "--fresh", "--port", str(PORT)],
                     stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).read())
            print("сервер готов:", {k: h[k] for k in ("ready", "mode", "model_loaded", "rules", "llm")}, "обращений:", h["storage"]["tickets"])
            return 0
        except OSError:
            time.sleep(0.5)
    print("сервер не поднялся")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
