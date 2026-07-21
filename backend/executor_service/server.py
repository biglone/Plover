from __future__ import annotations

import asyncio
import os

import grpc

from executor_service import executor_pb2_grpc
from executor_service.drivers import create_driver
from executor_service.service import ExecutorService


async def serve() -> None:
    server = grpc.aio.server()
    driver_name = os.getenv("PLOVER_EXECUTOR_DRIVER", "mock")
    bind_host = os.getenv("PLOVER_EXECUTOR_BIND", "[::]")
    bind_port = os.getenv("PLOVER_EXECUTOR_PORT", "50051")
    executor_pb2_grpc.add_ExecutorServicer_to_server(
        ExecutorService(create_driver(driver_name)),
        server,
    )
    server.add_insecure_port(f"{bind_host}:{bind_port}")
    await server.start()
    print(f"Plover Executor Service listening on {bind_host}:{bind_port} ({driver_name})")
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
