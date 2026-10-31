"""Рендер карточек видео (плашки, титулы частей, слайды) из assets/deck.html в PNG 1920x1080.

    python demo_video/scripts/render_deck.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
DV = ROOT / "demo_video"
OUT = DV / "work" / "deck"
HASHES = [f"plaques-{i}" for i in (1, 2, 3, 4)] + [f"sec-{i}" for i in (2, 3, 4, 5, 6, 7)] + [f"s-{i}" for i in range(1, 8)]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="msedge", headless=True, args=["--force-device-scale-factor=1"])
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, locale="ru-RU")
        page = await ctx.new_page()
        for h in HASHES:
            await page.goto("about:blank")
            await page.goto((DV / "assets" / "deck.html").as_uri() + "#" + h)
            await page.evaluate("document.fonts.ready.then(() => true)")
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(OUT / f"{h}.png"))
        await b.close()
    print("ok", len(HASHES))


if __name__ == "__main__":
    asyncio.run(main())
