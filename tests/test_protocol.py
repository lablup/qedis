from __future__ import annotations

from typing import AsyncContextManager, Callable, TypeAlias

import pytest

from qedis.protocol import RedisClientProtocol

ProtocolFactory: TypeAlias = Callable[
    [str, int], AsyncContextManager[RedisClientProtocol]
]


@pytest.mark.asyncio
async def test_simple_commands_split_stream(
    redis_instance: str,
    create_protocol: ProtocolFactory,
) -> None:
    async with create_protocol("127.0.0.1", 6379) as client:
        async with client.open_stream() as stream:
            reply = await stream.query(("HELLO", 3))
            assert reply[b"proto"] == 3
        async with client.open_stream() as stream:
            reply = await stream.query(("GET", "mykey"))
            assert reply is None
        async with client.open_stream() as stream:
            await stream.query(("SET", "mykey", "안녕하세요!"))
        async with client.open_stream() as stream:
            reply = await stream.query(("GET", "mykey"))
            assert reply == "안녕하세요!".encode("utf-8")


@pytest.mark.asyncio
async def test_simple_commands_single_stream(
    redis_instance: str,
    create_protocol: ProtocolFactory,
) -> None:
    async with create_protocol("127.0.0.1", 6379) as client:
        async with client.open_stream() as stream:
            reply = await stream.query(("HELLO", 3))
            assert reply[b"proto"] == 3
            reply = await stream.query(("GET", "mykey"))
            assert reply is None
            reply = await stream.query(("SET", "mykey", "안녕하세요!"))
            reply = await stream.query(("GET", "mykey"))
            assert reply == "안녕하세요!".encode("utf-8")


@pytest.mark.asyncio
async def test_pipeline_commands(
    redis_instance: str,
    create_protocol: ProtocolFactory,
) -> None:
    async with create_protocol("127.0.0.1", 6379) as client:
        async with client.open_stream() as stream:
            reply = await stream.query(("HELLO", 3))
            assert reply[b"proto"] == 3
            replies = await stream.pipeline([
                ("HSET", "mydata", "a", "hello"),
                ("HSET", "mydata", "b", "world"),
                ("HGETALL", "mydata"),
            ])
            assert replies[0] == 1
            assert replies[1] == 1
            assert replies[2] == {b"a": b"hello", b"b": b"world"}
            replies = await stream.pipeline([
                ("PING", "foo"),
                ("PING", "bar"),
            ])
            assert replies[0] == b"foo"
            assert replies[1] == b"bar"
