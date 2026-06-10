from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .preview import router as preview_router
from .routes import router as api_router
from .websocket import router as ws_router


def create_app(
    lifespan: Any = None,
    store: Any = None,
    scene_manager: Any = None,
    preview_manager: Any = None,
    sizes_preview_manager: Any = None,
    canvas: Any = None,
) -> FastAPI:
    app = FastAPI(title="LED Wall Engine", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ws_router)
    app.include_router(preview_router)
    app.include_router(api_router)

    if store is not None:
        app.state.store = store
    if scene_manager is not None:
        app.state.scene_manager = scene_manager
    if preview_manager is not None:
        app.state.preview_manager = preview_manager
    if sizes_preview_manager is not None:
        app.state.sizes_preview_manager = sizes_preview_manager
    if canvas is not None:
        app.state.canvas = canvas

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
