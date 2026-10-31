"""Видео-суфлёр: текст озвучки из DEMO_VOICEOVER_V2.md, слово за словом, рядом уменьшенная картинка того, что идёт на экране.

    python demo_video/scripts/teleprompter.py [--rate 1.0]

Выход: final/sentra_teleprompter_v2.mp4 (1920x1080, 30 к/с, без звука, 5 секунд отсчёта в начале).
Блок текста начинается в момент окна из заголовка блока; внутри окна слова идут в естественном темпе (около 2 слов/с).
Если блок не помещается в своё окно, следующий блок сдвигается, а в отчёте сказано на сколько.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
DV = ROOT / "demo_video"
WORK = DV / "work" / "tp"
FINAL = DV / "final"
MD = DV / "DEMO_VOICEOVER_V2.md"
SILENT = FINAL / "sentra_demo_grand_mobile_v2_silent.mp4"
COUNTDOWN = 5
VIDEO_END = 194.85          # после этого момента в окне картинки статичный слайд
TIME = re.compile(r"(\d+):(\d{2})(?:,(\d))?")
SLIDE_PNG = {"G1": "s-1", "G2": "s-2", "G3": "s-3", "G4": "s-4", "G5": "s-5", "G6": "s-6", "G7": "s-7"}


def tsec(m: re.Match) -> float:
    return int(m.group(1)) * 60 + int(m.group(2)) + (int(m.group(3)) / 10 if m.group(3) else 0)


def parse_md() -> list[dict]:
    blocks, cur = [], None
    for line in MD.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^(##|###) (.+)$", line)
        if h:
            title = h.group(2)
            times = [tsec(m) for m in TIME.finditer(title)]
            key = re.match(r"([A-G]\d?)\.", title)
            if title.startswith("Финал"):
                key = re.match(r"(Ф)", "Ф")
            silent = title.startswith("Титул")
            cur = None
            if len(times) >= 2 and (key or silent):
                cur = dict(key=key.group(1) if key else "", title=re.sub(r"\s*·.*$", "", title).strip(), start=times[0], end=times[1],
                           pause=bool(silent and not key), paras=[])
                blocks.append(cur)
            continue
        if cur is not None and line.startswith("> "):
            cur["paras"].append(line[2:].strip())
    return blocks


def word_dur(w: str, rate: float) -> float:
    letters = len(re.sub(r"[^\wё]", "", w, flags=re.I))
    d = 0.13 + 0.052 * letters
    if w.endswith((",", ";")):
        d += 0.18
    elif w.endswith((".", ":", "?", "!", "».", "».")):
        d += 0.4
    return d / rate


HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap&subset=cyrillic">
<style>
:root{--s0:#080A0A;--s1:#0C0F0E;--line:#2B3331;--t1:#EDF3F1;--t2:#A5B2AE;--t3:#76847F;--signal:#2FD9B5;}
*{box-sizing:border-box} html,body{margin:0;background:var(--s1)}
body{width:1920px;height:1080px;position:relative;overflow:hidden;font-family:Onest,'Segoe UI',sans-serif;color:var(--t1)}
.mono{font-family:'JetBrains Mono',Consolas,monospace}
#label{position:absolute;left:100px;top:70px;font-size:26px;letter-spacing:.14em;color:var(--signal)}
#text{position:absolute;left:100px;top:140px;width:1100px;max-height:800px;overflow:hidden;font-size:50px;line-height:1.45;font-weight:500}
#text p{margin:0 0 .7em}
.w{color:#6A7873;transition:none} .w.done{color:var(--t1)} .w.cur{color:var(--signal);text-decoration:underline;text-underline-offset:8px;text-decoration-thickness:4px}
#pause{position:absolute;left:100px;top:300px;width:1100px}
#pause .big{font-size:96px;font-weight:600;letter-spacing:-.01em} #pause .sm{margin-top:24px;font-size:38px;color:var(--t2);line-height:1.4}
#count{position:absolute;left:0;top:0;width:1920px;height:1080px;display:none;place-items:center;text-align:center;background:var(--s0)}
#count .n{font-size:360px;font-weight:600;color:var(--signal);line-height:1} #count .t{font-size:40px;color:var(--t2);margin-top:20px}
#pv{position:absolute;left:1260px;top:160px;width:560px;height:315px;border:1px solid var(--line);background:#000;overflow:hidden}
#pv img{width:100%;height:100%;object-fit:cover;display:none}
#pvcap{position:absolute;left:1260px;top:488px;width:560px;font-size:24px;color:var(--t3);line-height:1.4}
#next{position:absolute;left:100px;bottom:70px;width:1100px;font-size:26px;color:var(--t3);line-height:1.4}
#next b{color:var(--t2);font-weight:500}
#rec{position:absolute;right:100px;bottom:70px;font-size:24px;color:var(--t3)}
</style></head><body>
<div id="count"><div><div class="n" id="cn">5</div><div class="t">Нажмите запись и читайте, когда пойдёт текст</div></div></div>
<div id="label" class="mono"></div>
<div id="text"></div>
<div id="pause"><div class="big" id="pbig"></div><div class="sm" id="psm"></div></div>
<div id="pv"><img id="pvimg"></div><div id="pvcap"></div>
<div id="next"></div><div id="rec" class="mono">слова подсвечиваются в темпе чтения</div>
<script>
function render(s){
  document.getElementById('count').style.display = s.count ? 'grid' : 'none';
  if (s.count) { document.getElementById('cn').textContent = s.count; return; }
  document.getElementById('label').textContent = s.label;
  const t = document.getElementById('text'); t.innerHTML = '';
  document.getElementById('pause').style.display = s.pause ? 'block' : 'none';
  if (s.pause) { document.getElementById('pbig').textContent = 'Пауза, молчим'; document.getElementById('psm').textContent = s.pause; }
  if (s.paras) { let k = 0, cur = 0, acc = 0;
    s.paras.forEach((p, pi) => { if (s.idx >= acc && s.idx < acc + p.length) cur = pi; acc += p.length; });
    s.paras.forEach((p, pi) => { const start = k; const el = document.createElement('p');
      p.forEach(w => { const sp = document.createElement('span'); sp.className = 'w' + (k < s.idx ? ' done' : k === s.idx ? ' cur' : ''); sp.textContent = w + ' '; el.appendChild(sp); k++; });
      if (pi === cur || pi === cur + 1) t.appendChild(el); }); }
  const im = document.getElementById('pvimg');
  if (s.pv) { im.src = s.pv; im.style.display = 'block'; } else { im.style.display = 'none'; }
  document.getElementById('pvcap').textContent = s.cap || '';
  document.getElementById('next').innerHTML = s.next ? '<b>Дальше:</b> ' + s.next : '';
}
</script></body></html>
"""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=1.0, help="множитель темпа: 1.0 около 2 слов/с, меньше значит медленнее")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    blocks = parse_md()
    speak = [b for b in blocks if not b["pause"]]
    html = WORK / "tp.html"
    html.write_text(HTML, encoding="utf-8")
    deck = (DV / "work" / "deck").as_uri()

    # расписание: блоки идут подряд в естественном темпе, окна видео не соблюдаются (картинку подгоню под запись голоса)
    still = {"A": 14, "B": 40, "C": 70, "D": 115, "E": 160, "F": 188, "Ф": 245.5}
    frames: list[tuple[dict, float]] = []
    report = []
    for i in range(COUNTDOWN, 0, -1):
        frames.append(({"count": i}, 1.0))
    for bi, b in enumerate(blocks):
        nxt = next((x for x in blocks[bi + 1:] if not x["pause"]), None)
        if b["pause"]:
            n = re.search(r"части (\d)", b["title"])
            png = f"sec-{int(n.group(1)) + 1}" if n else "sec-6"
            frames.append(({"label": "ПАУЗА", "pause": f"На экране: {b['title']}", "pv": f"{deck}/{png}.png", "cap": "На экране сейчас",
                            "next": (nxt["title"] if nxt else "")}, 2.0))
            continue
        paras = [p.split() for p in b["paras"]]
        words = [w for p in paras for w in p]
        if b["key"] in SLIDE_PNG:
            pv = f"{deck}/{SLIDE_PNG[b['key']]}.png"
        else:
            png = WORK / f"still_{b['key']}.png"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(still[b["key"]]), "-i", str(SILENT), "-frames:v", "1", "-vf", "scale=1120:-1", str(png)], check=True)
            pv = png.as_uri()
        t = 0.0
        for k, w in enumerate(words):
            d = word_dur(w, args.rate)
            frames.append(({"label": f"БЛОК {b['key']} · {b['title'].split('. ', 1)[-1] if '. ' in b['title'] else b['title']}".upper(),
                            "paras": paras, "idx": k, "pv": pv, "cap": "На экране сейчас" if b["key"] not in SLIDE_PNG else "Слайд на экране",
                            "next": (nxt["title"] if nxt else "конец")}, d))
            t += d
        report.append({"block": b["key"], "words": len(words), "read_s": round(t, 1), "words_per_s": round(len(words) / t, 2)})
        frames.append(({"label": "ПАУЗА", "pause": "Вдох, 1 секунда", "pv": pv, "cap": "", "next": (nxt["title"] if nxt else "")}, 1.0))
    frames.append(({"label": "КОНЕЦ", "pause": "Спасибо, запись закончена", "next": ""}, 3.0))

    async with async_playwright() as p:
        br = await p.chromium.launch(channel="msedge", headless=True, args=["--force-device-scale-factor=1", "--allow-file-access-from-files"])
        ctx = await br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, locale="ru-RU")
        page = await ctx.new_page()
        await page.goto(html.as_uri())
        await page.evaluate("document.fonts.ready.then(() => true)")
        await page.wait_for_timeout(600)
        lines, cache = [], {}
        for i, (st, d) in enumerate(frames):
            key = json.dumps(st, ensure_ascii=False, sort_keys=True)
            png = cache.get(key)
            if png is None:
                await page.evaluate("s => render(s)", st)
                if st.get("pv"):
                    await page.wait_for_timeout(60)
                png = WORK / f"f{i:04d}.png"
                await page.screenshot(path=str(png))
                cache[key] = png
            lines += [f"file '{png.as_posix()}'", f"duration {d:.3f}"]
        lines.append(f"file '{png.as_posix()}'")
        await br.close()
    (WORK / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = FINAL / "sentra_teleprompter_v2.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(WORK / "list.txt"),
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
                    "-an", "-movflags", "+faststart", str(out)], check=True)
    (FINAL / "teleprompter_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in report:
        print(r)


if __name__ == "__main__":
    asyncio.run(main())
