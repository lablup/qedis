import argparse
import asyncio
import logging
import ssl
from dataclasses import dataclass
from typing import Any, cast

import hiredis
from aioquic.asyncio.client import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import (
    QuicEvent,
    StreamDataReceived,
    StreamReset,
)

logger = logging.getLogger("client")


@dataclass
class Waiter:
    future: asyncio.Future
    parser: hiredis.Reader
    reply_queue: list[Any] | None
    expected_reply_count: int = 1


class RedisClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._waiters: dict[int, Waiter] = dict()

    async def query(
        self, command: tuple[str | int | float | bytes | memoryview, ...]
    ) -> Any:
        stream_id = self._quic.get_next_available_stream_id()
        waiter = Waiter(
            future=self._loop.create_future(),
            parser=hiredis.Reader(notEnoughData=Ellipsis),
            reply_queue=None,
        )
        self._waiters[stream_id] = waiter
        data = hiredis.pack_command(command)  # type: ignore
        self._quic.send_stream_data(stream_id, data)
        logger.info("request (stream_id=%d): %r", stream_id, command)
        self.transmit()
        reply = await waiter.future
        logger.info("reply (stream_id=%d): %r", stream_id, reply)
        return reply

    async def pipeline(
        self, commands: list[tuple[str | int | float | bytes | memoryview, ...]]
    ) -> list[Any]:
        stream_id = self._quic.get_next_available_stream_id()
        replies = []
        waiter = Waiter(
            future=self._loop.create_future(),
            parser=hiredis.Reader(notEnoughData=Ellipsis),
            reply_queue=[],
            expected_reply_count=len(commands),
        )
        assert waiter.reply_queue is not None
        self._waiters[stream_id] = waiter
        for command in commands:
            data = hiredis.pack_command(command)  # type: ignore
            self._quic.send_stream_data(stream_id, data)
            logger.info("request (stream_id=%d): %r", stream_id, command)
        self.transmit()
        await waiter.future
        for reply in waiter.reply_queue:
            logger.info("reply (stream_id=%d): %r", stream_id, reply)
            replies.append(reply)
        return replies

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


async def main(
    configuration: QuicConfiguration,
    host: str,
    port: int,
) -> None:
    logger.debug(f"Connecting to {host}:{port}")
    async with connect(
        host,
        port,
        configuration=configuration,
        create_protocol=RedisClientProtocol,
    ) as client:
        client = cast(RedisClientProtocol, client)
        await client.query(("PING", "hello world"))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(client.query(("SET", "key", "value")))
            tg.create_task(client.query(("HSET", "data", "a", 123, "b", 456)))
            tg.create_task(client.query(("HSET", "data", "c", 789)))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(client.query(("GET", "key")))
            tg.create_task(client.query(("HGETALL", "data")))
        # Explicitly set the protocol version to 2.
        await client.pipeline([
            ("HELLO", 2),
            ("PING", "hello world, again"),
            ("PING", "foo"),
            ("PING", "bar"),
            ("SET", "k1", "한글"),
            ("GET", "k1"),
            ("DEL", "k1"),
            ("GET", "k1"),
            ("HGETALL", "data"),  # The reply is a flattend key-value pair list.
        ])
        # Explicitly set the protocol version to 3.
        await client.pipeline([
            ("HELLO", 3),
            ("PING", "hello world, again"),
            ("PING", "foo"),
            ("PING", "bar"),
            ("SET", "k1", "한글"),
            ("GET", "k1"),
            ("DEL", "k1"),
            ("GET", "k1"),
            ("HGETALL", "data"),  # The reply is a proper Python dict.
        ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redis over QUIC client")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="The remote peer's host name or IP address",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=6379,
        help="The remote peer's port number (UDP)",
    )
    parser.add_argument(
        "-k",
        "--insecure",
        action="store_true",
        help="Skip validation of server certificate",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase logging verbosity from INFO to DEBUG",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    configuration = QuicConfiguration(is_client=True)
    if args.insecure:
        configuration.verify_mode = ssl.CERT_NONE
    try:
        asyncio.run(
            main(
                configuration=configuration,
                host=args.host,
                port=args.port,
            )
        )
    except KeyboardInterrupt:
        pass
