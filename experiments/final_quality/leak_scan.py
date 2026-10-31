"""Сканер утечек данных кейса в то, что попадёт в репозиторий.

Что ищет (по отпечаткам, без вывода самих текстов):
  1. идентификаторы: ticket_id, reporter_hash, reported_hash из valid и train;
  2. тексты обращений игроков (нормализованные, от 40 символов) из valid и случайной части train;
  3. запрещённые типы файлов в индексе git и в истории (jsonl, pkl, gz, db, data/, models/).
Где ищет: отслеживаемые файлы, неигнорируемые новые файлы рабочего дерева и (для идентификаторов) вся история git.
Печатает только счётчики и пути, никогда не печатает найденные тексты.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT, norm_text  # noqa: E402

TEXT_EXT = {".py", ".md", ".json", ".txt", ".html", ".js", ".css", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".csv", ".svg",
            ".example", ""}


def git(*args, binary=False):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def worktree_files():
    tracked = git("ls-files").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    return tracked, untracked


def main():
    random.seed(C.SEED)
    ids, hashes, texts = set(), set(), set()
    for src, sample in ((ROOT / "data/tickets_valid.jsonl", 1.0), (ROOT / "data/tickets_train.jsonl.gz", 0.15)):
        for d in C.iter_jsonl(src):
            ids.add(d["ticket_id"])
            for k in ("reporter_hash", "reported_hash"):
                if d.get(k):
                    hashes.add(d[k])
            if random.random() <= sample:
                for m in d["messages"]:
                    if m["role"] != "admin":
                        t = norm_text(m.get("text") or "")
                        if len(t) >= 40:
                            texts.add(t)
    print(f"отпечатков: id={len(ids)} хэшей={len(hashes)} текстов>=40 симв.={len(texts)}", flush=True)

    tracked, untracked = worktree_files()
    out = {"forbidden_tracked": [], "id_hits": {}, "text_hits": {}, "files_scanned": 0}
    for f in tracked + untracked:
        p = ROOT / f
        if re.search(r"\.(jsonl|pkl|gz|db|db-wal|db-shm)$", f) or f.startswith(("data/", "models/")):
            out["forbidden_tracked"].append(f)
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT or p.stat().st_size > 5_000_000:
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        out["files_scanned"] += 1
        hit_ids = [i for i in ids if i in raw] if len(raw) > 0 else []
        hit_hashes = [h for h in hashes if h in raw]
        if hit_ids or hit_hashes:
            out["id_hits"][f] = {"ticket_ids": len(hit_ids), "hashes": len(hit_hashes)}
        nt = norm_text(raw)
        hits = sum(1 for t in texts if t in nt)
        if hits:
            out["text_hits"][f] = hits

    # история: идентификаторы и запрещённые файлы
    hist_files = sorted(set(l for l in git("log", "--all", "--name-only", "--pretty=format:").splitlines() if l))
    out["history_forbidden_paths"] = [f for f in hist_files if re.search(r"\.(jsonl|pkl|gz|db)$", f) or f.startswith(("data/", "models/"))
                                      or "template_suggestions" in f or "valid_gold" in f or "/private/" in f]
    sample_ids = random.sample(sorted(ids), 400)
    pat = "\n".join(sample_ids)
    r = subprocess.run(["git", "grep", "-l", "-F", "-f", "-", *git("rev-list", "--all").split()], cwd=ROOT, input=pat.encode(),
                       capture_output=True)
    out["history_id_hit_files"] = sorted({l.split(":", 1)[1] for l in r.stdout.decode("utf-8", "replace").splitlines() if ":" in l})
    # смысловые следы в истории: файлы с формулировками админов из выдачи
    out["history_derived_content_files"] = [f for f in out["history_forbidden_paths"] if "template_suggestions" in f]
    out["branches_containing_derived"] = [b.strip() for b in git("branch", "-a", "--contains", "4d7d55c").splitlines()]
    Path(C.OUT / "leak_scan.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
