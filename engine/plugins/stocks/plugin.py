from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from plugins._helpers import blit, load_font


class StocksApp(DisplayApp):
    id: ClassVar[str] = "stocks"
    name: ClassVar[str] = "Stock Ticker"
    description: ClassVar[str] = "Live prices and % change from Yahoo Finance as a color-coded scrolling ticker"
    icon: ClassVar[str] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3,18 8,11 13,14 20,5"/><polyline points="16,5 20,5 20,9"/></svg>'
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Stock Ticker",
        "properties": {
            "symbols": {
                "type": "array",
                "title": "Ticker symbols",
                "items": {"type": "string"},
                "default": ["AAPL", "MSFT", "GOOGL"],
            },
            "font_size": {
                "type": "integer",
                "title": "Font size",
                "default": 16,
                "minimum": 8,
                "maximum": 32,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 60,
                "minimum": 10,
            },
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 60,
            },
        },
        "required": ["symbols"],
    }

    def __init__(self, config: dict[str, Any], canvas: Canvas) -> None:
        super().__init__(config, canvas)
        self._quotes: list[dict[str, Any]] = []
        self._ticker_image: Image.Image | None = None
        self._ticker_w = 0
        self._offset = 0

    async def fetch_data(self) -> None:
        symbols: list[str] = self.config.get("symbols", [])
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_quote(client, s) for s in symbols],
                return_exceptions=True,
            )
        quotes = [r for r in results if isinstance(r, dict)]
        if quotes:
            self._quotes = quotes
            self._build_ticker_image()

    async def _fetch_quote(
        self, client: httpx.AsyncClient, symbol: str
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"range": "1d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            meta = data["chart"]["result"][0]["meta"]
            price: float = meta.get("regularMarketPrice", 0.0)
            prev: float = meta.get("previousClose") or meta.get(
                "chartPreviousClose", price
            )
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            return {"symbol": symbol, "price": price, "change_pct": change_pct}
        except Exception:
            return None

    def _build_ticker_image(self) -> None:
        font_size = int(self.config.get("font_size", 16))
        font = load_font(font_size)

        # Build colored text segments: symbol (white) + price+change (green/red)
        segments: list[tuple[str, tuple[int, int, int]]] = []
        for q in self._quotes:
            sign = "+" if q["change_pct"] >= 0 else ""
            color: tuple[int, int, int] = (
                (80, 220, 80) if q["change_pct"] >= 0 else (220, 80, 80)
            )
            segments.append((f"{q['symbol']} ", (200, 200, 200)))
            segments.append(
                (f"${q['price']:.2f} {sign}{q['change_pct']:.1f}%    ", color)
            )

        dummy = Image.new("RGB", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy)

        seg_widths = []
        total_w = 0
        for text, _ in segments:
            bbox = dummy_draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            seg_widths.append(w)
            total_w += w

        img = Image.new("RGB", (max(total_w, 1), self.canvas.height))
        draw = ImageDraw.Draw(img)

        x = 0
        for (text, color), w in zip(segments, seg_widths):
            bbox = dummy_draw.textbbox((0, 0), text, font=font)
            text_h = bbox[3] - bbox[1]
            y = (self.canvas.height - text_h) // 2 - bbox[1]
            draw.text((x, y), text, font=font, fill=color)
            x += w

        self._ticker_image = img
        self._ticker_w = total_w

    async def on_activate(self) -> None:
        self._offset = self.canvas.width

    async def render_frame(self) -> None:
        if self._ticker_image is None:
            self._draw_loading()
            return

        blit(self.canvas, self._ticker_image, self._offset)
        self._offset -= 2
        if self._offset < -self._ticker_w:
            self._offset = self.canvas.width

    def _draw_loading(self) -> None:
        font = load_font(14)
        dummy = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy)
        msg = "Fetching quotes..."
        bbox = draw.textbbox((0, 0), msg, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)
        x = (self.canvas.width - text_w) // 2
        y = (self.canvas.height - text_h) // 2 - bbox[1]
        draw.text((x, y), msg, font=font, fill=(80, 80, 80))
        blit(self.canvas, img)
