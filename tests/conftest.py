from __future__ import annotations

import asyncio
import contextlib
import secrets
import ssl
from pathlib import Path
from typing import AsyncContextManager, AsyncIterator, Callable, cast

import pytest
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration

from qedis.protocol import RedisClientProtocol


@pytest.fixture(scope="session", autouse=True)
def test_session_id() -> str:
    return f"qedis-test-session-{secrets.token_urlsafe(16)}"


@pytest.fixture
def test_case_id() -> str:
    return f"qedis-test-case-{secrets.token_urlsafe(16)}"


@pytest.fixture
async def redis_instance(test_case_id: str) -> AsyncIterator[str]:
    container_name = f"redis-{test_case_id}"
    sock_path = f"/tmp/redis-{test_case_id}.sock"
    proc = await asyncio.subprocess.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        "/tmp:/tmp",
        "redis:7-alpine",
        "redis-server",
        "--unixsocket",
        sock_path,
        "--unixsocketperm",
        "777",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    while not Path(sock_path).is_socket():
        await asyncio.sleep(0.1)
    proxy_proc = await asyncio.subprocess.create_subprocess_exec(
        "src/qedis-proxy/proxy",
        "-u",
        "unix",
        "-r",
        sock_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(0.1)

    yield sock_path

    proxy_proc.terminate()
    await proxy_proc.wait()
    proc = await asyncio.subprocess.create_subprocess_exec(
        "docker",
        "stop",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    proc = await asyncio.subprocess.create_subprocess_exec(
        "docker",
        "rm",
        "-v",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


@pytest.fixture
async def redis_sentinel_instance():
    # TODO: implement
    yield


@pytest.fixture
def create_protocol() -> Callable[[str, int], AsyncContextManager[RedisClientProtocol]]:
    @contextlib.asynccontextmanager
    async def _create_protocol(
        host: str, port: int
    ) -> AsyncIterator[RedisClientProtocol]:
        configuration = QuicConfiguration(is_client=True)
        configuration.verify_mode = ssl.CERT_NONE
        async with connect(
            host,
            port,
            configuration=configuration,
            create_protocol=RedisClientProtocol,
        ) as client:
            yield cast(RedisClientProtocol, client)

    return _create_protocol
