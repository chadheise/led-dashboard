from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, data: bytes) -> None:
        dead: set[WebSocket] = set()
        for ws in self._active:
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)
        self._active -= dead


manager = ConnectionManager()


@router.websocket("/ws/preview")
async def ws_preview(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Block until client disconnects; client sends nothing in this direction
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
