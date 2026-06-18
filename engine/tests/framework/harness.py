"""Generic registry + headless render harness for golden-snapshot suites.

An app opts in by registering a :class:`SnapshotSuite`: a set of named data
fixtures, a size matrix, and a render callable that turns (fixture, w, h) into
a :class:`RenderResult`. Tests and the contact-sheet tool both consume the
registry, so adding snapshot coverage for another app (stocks, weather, ...)
is one fixture module plus one ``register()`` call — no framework changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class RenderResult:
    """A rendered frame plus (optionally) the layout boxes that produced it."""

    image: Image.Image
    boxes: list[Any] | None = None  # list[layout.PlacedBox] once apps adopt Frame


@dataclass(frozen=True)
class SnapshotSuite:
    app_id: str
    fixtures: dict[str, Any]                       # fixture_id -> payload
    sizes: Sequence[tuple[int, int]]               # (w, h) applied to every fixture
    render: Callable[[Any, int, int], RenderResult]
    # Additional (fixture_id, w, h) cases beyond the core matrix, e.g. layout
    # tier edges that only need coverage from one representative fixture each.
    extra_cases: Sequence[tuple[str, int, int]] = field(default_factory=tuple)


# Standard size matrix: realistic panel widths at both panel heights.
CORE_SIZES: list[tuple[int, int]] = [
    (w, h) for h in (32, 64) for w in (64, 128, 192, 256, 320)
]

_REGISTRY: dict[str, SnapshotSuite] = {}

# Modules that register suites on import. Future apps append here.
_SUITE_MODULES = [
    "apps.sports.tests.fixtures",
    "apps.stocks.tests.fixtures",
    "apps.text.tests.fixtures",
    "apps.flights_overhead.tests.fixtures",
    "apps.flight_tracker.tests.fixtures",
    "apps.spotify.tests.fixtures",
    "apps.weather.tests.fixtures",
    "apps.countdown.tests.fixtures",
    "apps.world_clock.tests.fixtures",
]


def register(suite: SnapshotSuite) -> None:
    _REGISTRY[suite.app_id] = suite


def load_suites() -> None:
    import importlib

    for module in _SUITE_MODULES:
        importlib.import_module(module)


def get_suite(app_id: str) -> SnapshotSuite:
    if app_id not in _REGISTRY:
        load_suites()
    return _REGISTRY[app_id]


def all_cases(app_id: str) -> list[tuple[str, int, int]]:
    """Every (fixture_id, w, h) combination the suite covers."""
    suite = get_suite(app_id)
    cases = [
        (fixture_id, w, h)
        for fixture_id in suite.fixtures
        for (w, h) in suite.sizes
    ]
    cases.extend(suite.extra_cases)
    return cases


def render_case(app_id: str, fixture_id: str, w: int, h: int) -> RenderResult:
    suite = get_suite(app_id)
    return suite.render(suite.fixtures[fixture_id], w, h)


def case_id(fixture_id: str, w: int, h: int) -> str:
    return f"{fixture_id}_{w}x{h}"


# ── Whole-app frame rendering ──────────────────────────────────────────────────


def app_case_render(
    app_cls: type, *, freeze_datetime: str | None = None
) -> Callable[[Any, int, int], RenderResult]:
    """Build a SnapshotSuite render callable for config-driven app fixtures.

    Fixture payloads are ``{"config": {...}, "seed": callable | None}`` dicts.
    ``freeze_datetime`` (e.g. ``"apps.weather.app.datetime"``) pins
    ``datetime.now()`` in the app module to ``clock.FIXED_NOW`` during the
    render, for apps whose frames depend on the current time.
    """
    from contextlib import nullcontext

    from tests.framework.clock import frozen_time

    def _render(case: Any, w: int, h: int) -> RenderResult:
        ctx = frozen_time(freeze_datetime) if freeze_datetime else nullcontext()
        with ctx:
            image = render_app_frame(
                app_cls,
                dict(case.get("config") or {}),
                w,
                h,
                seed=case.get("seed") or (lambda app: None),
            )
        return RenderResult(image=image)

    return _render


def render_app_frame(
    app_cls: type,
    config: dict[str, Any],
    w: int,
    h: int,
    *,
    seed: Callable[[Any], None],
    global_config: dict[str, Any] | None = None,
    library_configs: dict[str, dict[str, Any]] | None = None,
) -> Image.Image:
    """Render one full frame of a DisplayApp headlessly, without network.

    The app is instantiated on a SimulatorCanvas; ``seed`` injects data
    directly (instead of calling ``fetch_data``), then a single
    ``render_frame()`` runs and the canvas pixels are returned as a PIL image.
    """
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    app = app_cls(config, canvas, global_config or {}, library_configs or {})
    seed(app)
    asyncio.run(app.render_frame())
    return Image.frombytes("RGB", (w, h), bytes(canvas._pixels))
