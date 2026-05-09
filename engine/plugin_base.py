from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from canvas.base import Canvas


class DisplayApp(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    icon: ClassVar[str] = ""  # inline SVG string; uses currentColor
    config_schema: ClassVar[dict[str, Any]]

    def __init__(self, config: dict[str, Any], canvas: Canvas) -> None:
        self.config = config
        self.canvas = canvas

    @property
    def refresh_interval(self) -> float:
        return float(self.config.get("refresh_interval", 60.0))

    @property
    def scene_duration(self) -> float:
        return float(self.config.get("scene_duration", 30.0))

    @abstractmethod
    async def fetch_data(self) -> None: ...

    @abstractmethod
    async def render_frame(self) -> None: ...

    async def on_activate(self) -> None:
        pass

    async def on_deactivate(self) -> None:
        pass
