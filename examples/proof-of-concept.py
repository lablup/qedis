import argparse
import asyncio
import logging
import ssl
from dataclasses import dataclass
from typing import cast

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


class RedisClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._waiters: dict[int, Waiter] = dict()

    async def query(
        self, command: tuple[str | int | float | bytes | memoryview, ...]
    ) -> None:
        data = hiredis.pack_command(command)  # type: ignore
        stream_id = self._quic.get_next_available_stream_id()
        self._quic.send_stream_data(stream_id, data)
        logger.info("Client request (stream_id=%d): %r", stream_id, command)
        waiter = Waiter(
            future=self._loop.create_future(),
            parser=hiredis.Reader(notEnoughData=Ellipsis),
        )
        self._waiters[stream_id] = waiter
        self.transmit()
        reply = await waiter.future
        logger.info("Server reply (stream_id=%d): %r", stream_id, reply)
        return reply

    def quic_event_received(self, event: QuicEvent) -> None:
        match event:
            case StreamReset():
                waiter = self._waiters.pop(event.stream_id, None)
                if waiter is None:
                    return
                if not waiter.future.done():
                    waiter.future.cancel()  # or inject a "connection reset" error
            case StreamDataReceived():
                waiter = self._waiters.get(event.stream_id, None)
                logger.debug("Protocol data-recv: %r", event)
                if waiter is None:
                    logger.debug(
                        "Protocol data-recv (stream_id=%d): waiter missing?",
                        event.stream_id,
                    )
                    return
                waiter.parser.feed(event.data)
                msg = waiter.parser.gets()
                if msg is Ellipsis:
                    # wait for more data
                    logger.debug(
                        "Protocol data-recv (stream_id=%d): waiting for more data",
                        event.stream_id,
                    )
                    return
                logger.debug("Protocol parsed-msg: %r", msg)
                self._quic.stop_stream(event.stream_id, 0)
                waiter.future.set_result(msg)


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
        await client.query(("PING", "hello-world"))
        await client.query(("PING", "hello-world"))
        await client.query(("PING", "hello-world"))
        await client.query(("PING", "hello-world"))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(client.query(("SET", "key", "value")))
            tg.create_task(client.query(("HSET", "data", "a", 123, "b", 456)))
            tg.create_task(client.query(("HSET", "data", "c", 789)))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(client.query(("GET", "key")))
            tg.create_task(client.query(("HGETALL", "data")))


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
