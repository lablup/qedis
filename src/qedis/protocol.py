from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Final

import hiredis
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import (
    QuicEvent,
    StreamDataReceived,
    StreamReset,
)

logger = logging.getLogger(__spec__.name)  # type: ignore[name-defined]


@dataclass
class Waiter:
    future: asyncio.Future
    parser: hiredis.Reader
    reply_queue: list[Any] | None
    expected_reply_count: int = 1


class RedisClientStream:
    stream_id: Final[int]
    proto: Final[RedisClientProtocol]

    def __init__(self, proto: RedisClientProtocol, stream_id: int) -> None:
        self.stream_id = stream_id
        self.proto = proto

    async def query(
        self, command: tuple[str | int | float | bytes | memoryview, ...]
    ) -> Any:
        loop = asyncio.get_running_loop()
        waiter = Waiter(
            future=loop.create_future(),
            parser=hiredis.Reader(notEnoughData=Ellipsis),
            reply_queue=None,
        )
        self.proto._waiters[self.stream_id] = waiter
        data = hiredis.pack_command(command)  # type: ignore
        self.proto._quic.send_stream_data(self.stream_id, data)
        logger.info("request (stream_id=%d): %r", self.stream_id, command)
        self.proto.transmit()
        reply = await waiter.future
        logger.info("reply (stream_id=%d): %r", self.stream_id, reply)
        return reply

    async def pipeline(
        self, commands: list[tuple[str | int | float | bytes | memoryview, ...]]
    ) -> list[Any]:
        loop = asyncio.get_running_loop()
        replies = []
        waiter = Waiter(
            future=loop.create_future(),
            parser=hiredis.Reader(notEnoughData=Ellipsis),
            reply_queue=[],
            expected_reply_count=len(commands),
        )
        assert waiter.reply_queue is not None
        self.proto._waiters[self.stream_id] = waiter
        for command in commands:
            data = hiredis.pack_command(command)  # type: ignore
            self.proto._quic.send_stream_data(self.stream_id, data)
            logger.info("request (stream_id=%d): %r", self.stream_id, command)
        self.proto.transmit()
        await waiter.future
        for reply in waiter.reply_queue:
            logger.info("reply (stream_id=%d): %r", self.stream_id, reply)
            replies.append(reply)
        return replies


class RedisClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._waiters: dict[int, Waiter] = dict()

    @contextlib.asynccontextmanager
    async def open_stream(self) -> AsyncIterator:
        stream_id = self._quic.get_next_available_stream_id()
        stream = RedisClientStream(self, stream_id)
        yield stream
        # TODO: close stream?

    def quic_event_received(self, event: QuicEvent) -> None:
        match event:
            case StreamReset():
                waiter = self._waiters.pop(event.stream_id, None)
                if waiter is None:
                    return
                logger.debug("Protocol: stream-reset (stream_id=%d)", event.stream_id)
                if not waiter.future.done():
                    waiter.future.cancel()  # or inject a "connection reset" error
            case StreamDataReceived():
                waiter = self._waiters.get(event.stream_id, None)
                logger.debug("Protocol: data-recv: %r", event)
                if waiter is None:
                    logger.debug(
                        "Protocol data-recv (stream_id=%d): waiter missing?",
                        event.stream_id,
                    )
                    return
                waiter.parser.feed(event.data)
                while waiter.parser.has_data():
                    msg = waiter.parser.gets()
                    if msg is Ellipsis:
                        # Need to receive more data
                        return
                    logger.debug("Protocol: parsed-msg: %r", msg)
                    if waiter.reply_queue is None:
                        waiter.future.set_result(msg)
                    else:
                        waiter.reply_queue.append(msg)
                        logger.debug(
                            "Protocol: enqueue-pipelined-reply (count=%d / expected=%d)",
                            len(waiter.reply_queue),
                            waiter.expected_reply_count,
                        )
                        if len(waiter.reply_queue) == waiter.expected_reply_count:
                            waiter.future.set_result(True)
