from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar


class Library(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    icon: ClassVar[str] = ""
    global_config_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @property
    def config(self) -> dict[str, Any]:
        return self._config
