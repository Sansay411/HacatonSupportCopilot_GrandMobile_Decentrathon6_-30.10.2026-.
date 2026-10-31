"""Проигрывание итогового файла настоящим плеером Edge от начала до конца (ускоренно, без звука).

    python demo_video/scripts/playback_check.py [файл]
Подтверждает, что браузерный плеер открывает файл, доходит до события ended и не сообщает об ошибке. Результат: final/playback_check.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
video = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo_video/final/sentra_demo_grand_mobile.mp4"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="msedge", headless=True)
        page = await (await b.new_context(viewport={"width": 1280, "height": 720})).new_page()
        await page.goto(video.as_uri())
        await page.wait_for_selector("video", timeout=15000)
        info = await page.evaluate("""async () => {
            const v = document.querySelector('video');
            v.muted = true; v.playbackRate = 8;
            const meta = { duration: v.duration, width: v.videoWidth, height: v.videoHeight };
            const done = new Promise(res => { v.addEventListener('ended', () => res('ended')); v.addEventListener('error', () => res('error')); });
            await v.play();
            const how = await Promise.race([done, new Promise(r => setTimeout(() => r('timeout'), 90000))]);
            const q = v.getVideoPlaybackQuality();
            return { ...meta, how, currentTime: v.currentTime, error: v.error ? v.error.message : null,
                     totalFrames: q.totalVideoFrames, droppedFrames: q.droppedVideoFrames, corrupted: q.corruptedVideoFrames || 0 };
        }""")
        await b.close()
    info["ok"] = info["how"] == "ended" and not info["error"] and abs(info["currentTime"] - info["duration"]) < 0.5
    (ROOT / "demo_video/final/playback_check.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


asyncio.run(main())
