from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/health")
async def ws_health(websocket: WebSocket) -> None:
    """Proves the WebSocket upgrade works end-to-end (through NPM in prod). Real progress
    hub lands in Phase C (PLAN.md §4.4); this is a plain echo for the Phase A exit criteria."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(f"pong:{message}")
    except WebSocketDisconnect:
        pass
