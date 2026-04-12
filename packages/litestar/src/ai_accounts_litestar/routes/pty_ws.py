from __future__ import annotations

import asyncio
import logging

from litestar import Controller, post, websocket
from litestar.connection import WebSocket

from ai_accounts_core.services.pty import PtyService

logger = logging.getLogger(__name__)


class PtyController(Controller):
    path = "/api/v1/pty"

    @post("/spawn", status_code=201)
    async def spawn(self, pty_service: PtyService, data: dict) -> dict:
        session_id, _ = await pty_service.spawn(
            backend_id=data["backend_id"],
            command=tuple(data["command"]),
            cols=data.get("cols", 80),
            rows=data.get("rows", 24),
        )
        return {"session_id": session_id}

    @post("/{session_id:str}/kill", status_code=200)
    async def kill(self, pty_service: PtyService, session_id: str) -> dict:
        await pty_service.kill(session_id)
        return {"status": "killed"}

    @post("/{session_id:str}/resize", status_code=200)
    async def resize(self, pty_service: PtyService, session_id: str, data: dict) -> dict:
        handle = pty_service.attach(session_id)
        if handle is None:
            return {"status": "error", "message": "session not found"}
        await handle.resize(data.get("cols", 80), data.get("rows", 24))
        return {"status": "ok"}


@websocket("/ws/pty/{session_id:str}")
async def pty_websocket(
    socket: WebSocket, pty_service: PtyService, session_id: str
) -> None:
    await socket.accept()
    handle = pty_service.attach(session_id)
    if handle is None:
        await socket.send_data(b"session not found", mode="binary")
        await socket.close()
        return

    async def reader() -> None:
        try:
            async for chunk in handle.read():
                await socket.send_data(chunk, mode="binary")
        except Exception:
            logger.debug("pty reader ended for %s", session_id)

    async def writer() -> None:
        try:
            while True:
                data = await socket.receive_data(mode="binary")
                if isinstance(data, bytes):
                    await handle.write(data)
        except Exception:
            logger.debug("pty writer ended for %s", session_id)

    read_task = asyncio.create_task(reader())
    write_task = asyncio.create_task(writer())
    try:
        await asyncio.gather(read_task, write_task, return_exceptions=True)
    finally:
        read_task.cancel()
        write_task.cancel()
        await socket.close()
