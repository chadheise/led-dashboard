"""Dev-only hot-reload watcher. Enable with HOT_RELOAD=true."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import PythonFilter, awatch

if TYPE_CHECKING:
    from scene_manager import SceneManager
    from state import StateStore

logger = logging.getLogger(__name__)


def _evict_app_modules() -> None:
    to_remove = [
        k for k in list(sys.modules)
        if k == "apps" or k.startswith("apps.")
        or k == "libraries" or k.startswith("libraries.")
    ]
    for k in to_remove:
        del sys.modules[k]


def _rebuild_registries(app_registry: dict, library_registry: dict) -> None:
    import apps as apps_pkg
    import libraries as libs_pkg

    app_registry.clear()
    app_registry.update(apps_pkg.APP_REGISTRY)

    library_registry.clear()
    library_registry.update(libs_pkg.LIBRARY_REGISTRY)


async def start_hot_reload_watcher(
    store: StateStore,
    scene_manager: SceneManager,
    app_registry: dict,
    library_registry: dict,
    engine_root: Path,
) -> None:
    """Long-running coroutine; runs as an asyncio.Task inside lifespan."""
    watch_dirs = [engine_root / "apps", engine_root / "libraries"]
    logger.info("Hot-reload watching: %s", [str(d) for d in watch_dirs])

    async for _changes in awatch(*watch_dirs, watch_filter=PythonFilter()):
        logger.info("Hot-reload: .py change detected, reloading...")
        _evict_app_modules()
        try:
            _rebuild_registries(app_registry, library_registry)
        except SyntaxError as exc:
            logger.error(
                "Hot-reload: syntax error in %s line %s — keeping old code",
                exc.filename, exc.lineno,
            )
            continue
        except Exception as exc:
            logger.error("Hot-reload: import error — %s", exc)
            continue

        resolved = store.resolve()
        if not resolved:
            logger.info("Hot-reload: no active playlist, skipping scene reinit")
            continue

        from scene_manager import PlaylistEntry
        entries = [
            PlaylistEntry(
                app_id=e["app_id"],
                config=e["config"],
                duration=e["duration"],
                global_config=e.get("global_config", {}),
                library_configs=e.get("library_configs", {}),
            )
            for e in resolved
        ]
        try:
            await scene_manager.set_playlist(entries)
            logger.info("Hot-reload: complete (%d scene(s) reinitialised)", len(entries))
        except Exception as exc:
            logger.error("Hot-reload: set_playlist failed — %s", exc)
