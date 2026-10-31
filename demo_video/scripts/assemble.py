"""Монтаж итогового видео из записанных сцен: брендовые карточки, плавные переходы, главы, без звука.

    python demo_video/scripts/assemble.py

Вход: demo_video/raw/01_*.mp4 ... 06_*.mp4 (записи браузера). Карточки собираются из admin_ui/assets/sentra-lockup.svg.
Выход: demo_video/final/sentra_demo_grand_mobile.mp4 и final/timeline.json (таймкоды для DEMO_VOICEOVER.md).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
DV = ROOT / "demo_video"
RAW, FINAL, WORK = DV / "raw", DV / "final", DV / "work"
XF = 0.5          # длительность перекрёстного затухания между сценами
XF_END = 0.8      # последний переход к финальной карточке мягче
W, H, FPS = 1920, 1080, 30

SCENES = [   # (файл, название сцены в видео)
    ("00_brand_intro.mp4", "Intro: бренд"),
    ("01_command_center.mp4", "Сцена 1: командный центр"),
    ("02_triage.mp4", "Сцена 2: настоящий триаж"),
    ("03_safety.mp4", "Сцена 3: защита и проверка текста"),
    ("04_escalation.mp4", "Сцена 4: обязательная эскалация"),
    ("05_workspace.mp4", "Сцена 5: рабочее место модератора"),
    ("06_command_center_outro.mp4", "Сцена 6: командный центр"),
    ("07_brand_outro.mp4", "Outro: бренд"),
]
CARD_SECONDS = {"00_brand_intro.mp4": 2.8, "07_brand_outro.mp4": 3.6}
# Из записей срезается только неподвижное начало (курсор ещё не двигался) и хвост после последнего действия.
# Ни одно действие и ни один ответ сервера не вырезаются.
TRIM_HEAD = {"02_triage.mp4": 0.55, "03_safety.mp4": 0.55, "04_escalation.mp4": 0.55, "05_workspace.mp4": 0.55,
             "06_command_center_outro.mp4": 0.55}
TRIM_TAIL = {"01_command_center.mp4": 0.2, "02_triage.mp4": 0.2, "03_safety.mp4": 0.2, "04_escalation.mp4": 0.2,
             "05_workspace.mp4": 0.2, "06_command_center_outro.mp4": 0.2}


def run(cmd: list[str], **kw):
    subprocess.run(cmd, check=True, **kw)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


async def render_cards():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="msedge", headless=True, args=["--force-device-scale-factor=1"])
        ctx = await b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, locale="ru-RU")
        page = await ctx.new_page()
        for name, frag in (("card_intro", ""), ("card_outro", "#outro")):
            await page.goto("about:blank")
            await page.goto((DV / "assets" / "brand_card.html").as_uri() + frag)
            await page.evaluate("document.fonts.ready.then(() => true)")
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(WORK / f"{name}.png"))
        await b.close()


def card_clip(png: Path, out: Path, seconds: float):
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(png), "-t", f"{seconds}",
         "-vf", f"scale={W}:{H}:flags=lanczos+accurate_rnd:in_range=full:out_range=limited:out_color_matrix=bt709,format=yuv420p",
         "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-color_range", "tv", str(out)])


def main():
    WORK.mkdir(exist_ok=True)
    FINAL.mkdir(exist_ok=True)
    asyncio.run(render_cards())
    card_clip(WORK / "card_intro.png", RAW / "00_brand_intro.mp4", CARD_SECONDS["00_brand_intro.mp4"])
    card_clip(WORK / "card_outro.png", RAW / "07_brand_outro.mp4", CARD_SECONDS["07_brand_outro.mp4"])

    files = [RAW / f for f, _ in SCENES]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise SystemExit("нет записей: " + ", ".join(missing))
    raw_durs = [duration(f) for f in files]
    heads = [TRIM_HEAD.get(f.name, 0.0) for f in files]
    tails = [TRIM_TAIL.get(f.name, 0.0) for f in files]
    durs = [d - h - t for d, h, t in zip(raw_durs, heads, tails)]
    xfs = [XF] * (len(files) - 2) + [XF_END]            # переход i -> i+1
    # начало каждого клипа на итоговой шкале
    starts, t = [], 0.0
    for i, d in enumerate(durs):
        starts.append(t)
        if i < len(xfs):
            t += d - xfs[i]
    total = starts[-1] + durs[-1]

    parts = [f"[{i}:v]trim=start={heads[i]:.3f}:end={raw_durs[i] - tails[i]:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[t{i}]"
             for i in range(len(files))]
    prev = "[t0]"
    for i in range(1, len(files)):
        out = f"[v{i}]"
        parts.append(f"{prev}[t{i}]xfade=transition=fade:duration={xfs[i - 1]}:offset={starts[i]:.3f}{out}")
        prev = out
    graph = ";".join(parts)

    # главы: граница сцены посередине перекрёстного перехода
    bounds = [0.0] + [starts[i] + xfs[i - 1] / 2 for i in range(1, len(files))] + [total]
    meta = [";FFMETADATA1", "title=Sentra by LGTM: демонстрация для Grand Mobile"]
    for i, (_, title) in enumerate(SCENES):
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(bounds[i] * 1000)}", f"END={int(bounds[i + 1] * 1000) - 1}", f"title={title}"]
    (WORK / "chapters.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")

    out = FINAL / "sentra_demo_grand_mobile.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for f in files:
        cmd += ["-i", str(f)]
    cmd += ["-i", str(WORK / "chapters.txt"), "-filter_complex", graph, "-map", prev, "-map_metadata", f"{len(files)}",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-r", str(FPS), "-an",
            "-movflags", "+faststart", "-metadata", "comment=Sentra by LGTM demo, no audio", str(out)]
    run(cmd)

    timeline = {"file": str(out.relative_to(ROOT)).replace("\\", "/"), "total_s": round(total, 2),
                "scenes": [{"file": f, "title": title, "clip_s": round(raw_durs[i], 2), "used_s": round(durs[i], 2), "starts": round(starts[i], 2),
                            "from": round(bounds[i], 2), "to": round(bounds[i + 1], 2)} for i, (f, title) in enumerate(SCENES)]}
    (FINAL / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(timeline, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
