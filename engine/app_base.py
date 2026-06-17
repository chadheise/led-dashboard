from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from canvas.base import Canvas
from grid import SizeConstraints


class DisplayApp(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    icon: ClassVar[str] = ""  # inline SVG string; uses currentColor
    config_schema: ClassVar[dict[str, Any]]
    global_config_schema: ClassVar[dict[str, Any]] = {}  # app-level params (API keys, defaults)
    libraries: ClassVar[list[str]] = []  # library IDs this app depends on
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints()  # no constraints by default

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.canvas = canvas
        self.global_config: dict[str, Any] = global_config or {}
        self.library_configs: dict[str, dict[str, Any]] = library_configs or {}

    @property
    def refresh_interval(self) -> float:
        return float(self.config.get("refresh_interval", 60.0))

    @abstractmethod
    async def fetch_data(self) -> None: ...

    @abstractmethod
    async def render_frame(self) -> None: ...

    async def should_display(self) -> bool:
        return True

    async def should_pin(self) -> bool:
        """Return True to request the scene manager keep this scene on screen.

        When True, the scene manager will not rotate away from this scene and
        will immediately jump to it if another scene is currently active.
        """
        return False

    async def on_activate(self) -> None:
        pass

    async def on_deactivate(self) -> None:
        pass
