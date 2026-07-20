from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import WebSocket, WebSocketDisconnect


class VncTargetError(ValueError):
    """Raised when a VNC target is missing or malformed."""


@dataclass(frozen=True)
class VncTarget:
    host: str
    port: int

    @classmethod
    def parse(cls, value: str) -> "VncTarget":
        raw = value.strip()
        if not raw:
            raise VncTargetError("VNC target cannot be empty")
        if raw.startswith("["):
            host, separator, port_text = raw[1:].partition("]:")
            if not separator:
                raise VncTargetError("IPv6 VNC target must use [host]:port")
        else:
            if ":" not in raw:
                raise VncTargetError("VNC target must use host:port")
            host, port_text = raw.rsplit(":", 1)
        if not host:
            raise VncTargetError("VNC target host cannot be empty")
        try:
            port = int(port_text)
        except ValueError as error:
            raise VncTargetError("VNC target port must be an integer") from error
        if not 1 <= port <= 65535:
            raise VncTargetError("VNC target port must be between 1 and 65535")
        return cls(host=host, port=port)


async def proxy_vnc(websocket: WebSocket, target: VncTarget) -> None:
    await websocket.accept()
    reader, writer = await asyncio.open_connection(target.host, target.port)

    async def browser_to_vnc() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                writer.write(message["bytes"])
            elif message.get("text") is not None:
                writer.write(message["text"].encode("utf-8"))
            await writer.drain()

    async def vnc_to_browser() -> None:
        while True:
            payload = await reader.read(64 * 1024)
            if not payload:
                return
            await websocket.send_bytes(payload)

    tasks = [
        asyncio.create_task(browser_to_vnc()),
        asyncio.create_task(vnc_to_browser()),
    ]
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            error = task.exception()
            if error and not isinstance(error, (WebSocketDisconnect, ConnectionError, OSError)):
                raise error
        for task in pending:
            task.cancel()
    finally:
        writer.close()
        await writer.wait_closed()

