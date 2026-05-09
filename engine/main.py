import asyncio
import colorsys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
import yaml
from fastapi import FastAPI

from api.server import create_app
from api.websocket import manager
from canvas.simulator import SimulatorCanvas


def _load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _draw_test_frame(canvas: SimulatorCanvas, frame: int) -> None:
    """Rainbow bands that scroll across the display over time."""
    t = frame * 0.008
    for x in range(canvas.width):
        hue = (x / canvas.width + t) % 1.0
        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        r, g, b = int(r_f * 255), int(g_f * 255), int(b_f * 255)
        for y in range(canvas.height):
            canvas.set_pixel(x, y, r, g, b)


async def _render_loop(canvas: SimulatorCanvas, fps: int) -> None:
    interval = 1.0 / fps
    frame = 0
    while True:
        canvas.clear()
        _draw_test_frame(canvas, frame)
        await canvas.render()
        frame += 1
        await asyncio.sleep(interval)


def main() -> None:
    cfg = _load_config()
    display_cfg = cfg["display"]
    server_cfg = cfg["server"]

    canvas = SimulatorCanvas(
        display_cfg["width"], display_cfg["height"], manager.broadcast
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(
            _render_loop(canvas, display_cfg["fps"])
        )
        try:
            yield
        finally:
            task.cancel()

    app = create_app(lifespan=lifespan)
    uvicorn.run(app, host=server_cfg["host"], port=server_cfg["port"])


if __name__ == "__main__":
    main()
