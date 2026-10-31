"""Прогон синтетических проб через pipeline и подсчёт: сценарий из допустимых, запретные подстроки, инварианты.

    python experiments/draft_audit/run_probes.py [--group account] [--full] [--json out.json] [--fixture] [--quiet]

Без --fixture нужны data/ и models/ (настоящие правила и модели), с --fixture берутся тестовые правила без моделей.
"""
from __future__ import annotations

import argparse
import json

import common as C
from probes import PROBES

ap = argparse.ArgumentParser()
ap.add_argument("--group")
ap.add_argument("--full", action="store_true")
ap.add_argument("--json")
ap.add_argument("--fixture", action="store_true", help="тестовые правила tests/fixtures вместо data/")
ap.add_argument("--quiet", action="store_true", help="печатать только провалы и итог")
ap.add_argument("--tree", help="взять код copilot/ из этой папки (например, распакованный HEAD); данные и модели из рабочей копии")
a = ap.parse_args()

if a.tree:
    import os
    import sys
    os.environ["COPILOT_DATA"] = str(C.ROOT / "data")
    os.environ["COPILOT_MODELS"] = str(C.ROOT / "models")
    sys.path.insert(0, a.tree)

from copilot.pipeline import Copilot  # noqa: E402

if a.fixture:
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    shutil.copy(C.ROOT / "tests/fixtures/rules_mini.json", f"{tmp}/rules.json")
    cp = Copilot(tmp, f"{tmp}/no_models")
else:
    cp = Copilot()

out, scored, passed = [], 0, 0
inv_bad = []
for i, p in enumerate(PROBES):
    if a.group and p["group"] != a.group:
        continue
    payload = {"kind": p["kind"], "messages": [{"role": "player", "text": p["text"]}]}
    if p["server_lang"]:
        payload["server_lang"] = p["server_lang"]
    if p["images"] is not None:
        payload["images_count"] = p["images"]
    if p["nick"]:
        payload["reported_nick"] = p["nick"]
    r = cp.triage(payload, use_dedup=False)
    reply = r["draft_reply"]["text"]
    intent = r["_meta"]["intent"]
    status = "-"
    if p["ok"] is not None:
        scored += 1
        status = "ok" if intent in p["ok"] else "FAIL"
        passed += status == "ok"
    for f in p["forbid"]:
        if f.lower() in reply.lower():
            status = "FAIL"
    problems = []
    if C.PROMISE.search(reply):
        problems.append("promise")
    if C.HANDOFF.search(reply) and not r["needs_human"]:
        problems.append("handoff_without_human")
    if any(not cp.rules.exists(c) for c in r["draft_reply"]["cited"]):
        problems.append("bad_cite")
    if problems:
        inv_bad.append((i, problems))
    rec = {"i": i, "group": p["group"], "text": p["text"], "status": status, "category": r["category"], "intent": intent,
           "needs_human": r["needs_human"], "lang": r["draft_reply"]["lang"], "reply": reply,
           "cited": r["draft_reply"]["cited"], "reasons": r["reasons"], "problems": problems}
    out.append(rec)
    if a.quiet and status != "FAIL" and not problems:
        continue
    body = reply if a.full else reply[:170]
    print(f"[{i}] {status:4} {p['group']}/{p['kind']} «{p['text']}» -> {rec['category']} / {intent} / human={rec['needs_human']}\n      {body}")
print(f"\nпроб с ожиданием: {scored}, сценарий допустимый: {passed}; нарушений инвариантов: {len(inv_bad)} {inv_bad}")
if a.json:
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
