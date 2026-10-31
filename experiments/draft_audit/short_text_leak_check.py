"""Дополнение к experiments/final_quality/leak_scan.py: точное совпадение коротких строк из тестов, проб и документов с реальными
обращениями (valid и train). Сканер утечек ищет тексты от 40 символов, а короткие реплики игроков тоже данные кейса.
Печатает только число совпадений и файл, сами тексты не печатает.

    python experiments/draft_audit/short_text_leak_check.py
"""
from __future__ import annotations

import gzip
import json
import re
import sys

import common as C

import importlib.util  # noqa: E402

# одноимённый common.py лежит и в experiments/final_quality: грузим его под другим именем
_spec = importlib.util.spec_from_file_location("fq_common", C.ROOT / "experiments" / "final_quality" / "common.py")
_fq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fq)
norm_text = _fq.norm_text

FILES = ["tests/test_draft_audit.py", "tests/fixtures/draft_probes.py", "docs/audit/DRAFT_QUALITY.md", "docs/DEMO_SCRIPT.md",
         "README.md", "REPORT.md", "copilot/drafts.py", "copilot/selfcheck.py",
         "docs/audit/FINAL_POLISH.md", "tests/test_final_polish.py", "tests/test_ticket_identity.py", "tests/fixtures/rag_cases.py",
         "tests/test_replay_and_brevity.py", "tests/test_redteam_audit.py", "tests/test_evidence_negation.py"]
VERBOSE = "-v" in sys.argv
MIN_WORDS = 5                    # фразы короче пяти слов («не согласен с наказанием») встречаются у многих игроков и ничего не раскрывают
MIN_LEN = 6                      # короче: «оск», «+», «помогите» слишком общие, это слова, а не тексты

real: set[str] = set()
for p in (C.ROOT / "data" / "tickets_valid.jsonl", C.ROOT / "data" / "tickets_train.jsonl.gz"):
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = norm_text(" ".join(m.get("text", "") for m in r["messages"] if m.get("role", "player") == "player"))
            if len(t) >= MIN_LEN:
                real.add(t)
print("реальных нормализованных текстов:", len(real))
total = 0
for rel in FILES:
    s = (C.ROOT / rel).read_text(encoding="utf-8")
    hits = 0
    for lit in set(re.findall(r'"([^"\n]{%d,200})"' % MIN_LEN, s)) | set(re.findall(r"«([^»\n]{%d,200})»" % MIN_LEN, s)):
        if re.search(r"[а-яёa-z]", lit, re.I) and len(lit.split()) >= MIN_WORDS and norm_text(lit) in real:
            hits += 1
            if VERBOSE:
                print("   совпало:", lit)
    total += hits
    print(f"{rel}: {hits}")
print("итого совпадений с реальными текстами:", total)
sys.exit(1 if total else 0)
