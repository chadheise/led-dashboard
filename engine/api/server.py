from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .websocket import router as ws_router


def create_app(lifespan: Any = None) -> FastAPI:
    app = FastAPI(title="LED Wall Engine", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ws_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
