from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar


class Library(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    icon: ClassVar[str] = ""
    global_config_schema: ClassVar[dict[str, Any]] = {}
    # Libraries that track runtime usage (API budget/cost, caches) set this so
    # the settings UI knows to fetch and render a live status panel for them.
    has_status: ClassVar[bool] = False

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def get_status(self) -> dict[str, Any] | None:
        """Live usage status for the settings UI (budget/cost, cache, etc.).

        Returns ``None`` when the library has nothing to report. Subclasses that
        set ``has_status = True`` override this. The shape is a small, render-
        agnostic structure::

            {
                "note": "optional context line",
                "sections": [
                    {"label": "Section", "items": [
                        {"label": "Field", "value": "string or number"},
                        {"label": "When", "value": <epoch>, "kind": "timestamp"},
                    ]},
                ],
            }
        """
        return None
