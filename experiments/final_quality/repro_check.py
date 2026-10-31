"""Проверка воспроизводимости в чистом окружении: POST /triage по HTTP, make predict, запуск без приватных файлов.

Запуск (python из ЧИСТОГО venv, поставленного только из requirements.txt):
    python repro_check.py --checkout <чистая копия HEAD без data/ и models/> --data <путь к data> --models <путь к models>
Что делает:
  1. без data/ и models/: serve.py поднимается, /health честно говорит, чего нет, POST /triage отвечает 503 (ничего не подменяется);
  2. serve.py --fixture: POST /triage по контракту работает на тестовых правилах;
  3. с копиями data/ и models/ в чистой копии: POST /triage на реальных правилах, контракт, 3 вызова с разными языками;
  4. scripts/predict.py (то, что делает make predict) дважды: 1000 строк, схема, результаты побайтно одинаковые.
Копии данных кейса кладутся только во временную чистую копию и удаляются в конце.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REQUIRED = ("lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human", "confidence", "reasons")
PRIORITIES = {"p0", "p1", "p2", "p3"}


def call(url, payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def contract_problems(resp) -> list[str]:
    bad = [k for k in REQUIRED if k not in resp]
    if resp.get("priority") not in PRIORITIES:
        bad.append("priority_value")
    d = resp.get("draft_reply") or {}
    if not isinstance(d.get("text"), str) or not isinstance(d.get("cited"), list):
        bad.append("draft_reply_shape")
    if not isinstance(resp.get("needs_human"), bool):
        bad.append("needs_human_type")
    if not isinstance(resp.get("confidence"), (int, float)) or not 0 <= resp["confidence"] <= 1:
        bad.append("confidence_range")
    return bad


class Server:
    def __init__(self, root: Path, port: int, extra=(), env=None):
        e = dict(os.environ)
        e.update(env or {})
        e["COPILOT_DB"] = str(root / "var" / f"repro_{port}.db")
        self.p = subprocess.Popen([sys.executable, "scripts/serve.py", "--port", str(port), *extra], cwd=root, env=e,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = f"http://127.0.0.1:{port}"

    def wait(self, tries=60):
        for _ in range(tries):
            try:
                return call(self.base + "/health")
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("сервер не поднялся")

    def stop(self):
        # serve.py запускает uvicorn дочерним процессом: на Windows terminate() родителя его не останавливает
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"], capture_output=True)
        else:
            self.p.terminate()
        try:
            self.p.wait(10)
        except subprocess.TimeoutExpired:
            self.p.kill()


SAMPLES = [
    {"kind": "complaint", "server_lang": "ru", "messages": [{"role": "player", "text": "Test_Player оскорбил меня в чате, скрин есть"}]},
    {"kind": "complaint", "server_lang": "uz", "messages": [{"role": "player", "text": "Test_Player meni haqorat qildi, skrin bor"}]},
    {"kind": "report", "server_lang": "kk", "messages": [{"role": "player", "text": "көмектесіңіз, көлігім аударылып қалды"}]},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.checkout)
    (root / "var").mkdir(exist_ok=True)
    res = {"python": sys.version.split()[0], "checkout_files": sum(1 for _ in root.rglob("*") if _.is_file())}
    assert not (root / "data").exists() and not (root / "models").exists(), "чистая копия должна быть без data/ и models/"

    # 1. без приватных файлов
    s = Server(root, 18101)
    try:
        code, health = s.wait()
        triage_code, triage_body = call(s.base + "/triage", SAMPLES[0])
        res["no_private_files"] = {"health_http": code, "health_mode": health.get("mode") or health.get("status"),
                                   "health_missing": health.get("missing"), "triage_http": triage_code,
                                   "triage_error_text": str(triage_body)[:160]}
    finally:
        s.stop()

    # 2. --fixture
    s = Server(root, 18102, extra=("--fixture",))
    try:
        s.wait()
        out = []
        for smp in SAMPLES:
            c, body = call(s.base + "/triage", smp)
            out.append({"http": c, "contract_problems": contract_problems(body), "lang": body.get("lang"),
                        "category": body.get("category"), "needs_human": body.get("needs_human")})
        c, health = call(s.base + "/health")
        res["fixture_mode"] = {"health_http": c, "rules_synthetic": health.get("rules_synthetic"), "calls": out}
    finally:
        s.stop()

    # 3. с копиями data/ и models/
    try:
        shutil.copytree(a.data, root / "data")
        shutil.copytree(a.models, root / "models")
        s = Server(root, 18103)
        try:
            c, health = s.wait()
            out, lat = [], []
            for smp in SAMPLES:
                t0 = time.perf_counter()
                cc, body = call(s.base + "/triage", smp)
                lat.append((time.perf_counter() - t0) * 1000)
                out.append({"http": cc, "contract_problems": contract_problems(body), "lang": body.get("lang"),
                            "category": body.get("category"), "draft_lang": (body.get("draft_reply") or {}).get("lang")})
            res["with_data_and_models"] = {"health_http": c, "health_mode": health.get("mode"), "calls": out,
                                           "latency_ms_first_calls": [round(x, 1) for x in lat]}
        finally:
            s.stop()

        # 4. make predict дважды
        def sha(p):
            return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]

        outs = []
        for k in (1, 2):
            o = root / f"pred_{k}.jsonl"
            t0 = time.time()
            r = subprocess.run([sys.executable, "scripts/predict.py", "--in", str(root / "data/tickets_valid.jsonl"), "--out", str(o)],
                               cwd=root, capture_output=True, text=True)
            outs.append({"exit": r.returncode, "seconds": round(time.time() - t0, 1), "sha": sha(o) if o.exists() else None})
        rows = [json.loads(l) for l in (root / "pred_1.jsonl").read_text(encoding="utf-8").splitlines() if l]
        probs = sum(bool(contract_problems(r)) for r in rows)
        res["make_predict"] = {"runs": outs, "identical_output": outs[0]["sha"] == outs[1]["sha"] and outs[0]["sha"] is not None,
                               "rows": len(rows), "rows_with_contract_problems": probs,
                               "has_internal_meta_field": any("_meta" in r for r in rows)}
    finally:
        for d in ("data", "models"):
            shutil.rmtree(root / d, ignore_errors=True)
        for f in root.glob("pred_*.jsonl"):
            f.unlink()
    res["private_copies_removed"] = not (root / "data").exists() and not (root / "models").exists()
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
