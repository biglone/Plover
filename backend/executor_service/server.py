from __future__ import annotations

import asyncio

import grpc

from executor_service import executor_pb2_grpc
from executor_service.driver import MockEnvironmentDriver
from executor_service.service import ExecutorService


async def serve() -> None:
    server = grpc.aio.server()
    executor_pb2_grpc.add_ExecutorServicer_to_server(
        ExecutorService(MockEnvironmentDriver()),
        server,
    )
    server.add_insecure_port("[::]:50051")
    await server.start()
    print("Plover Executor Service listening on :50051")
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())

