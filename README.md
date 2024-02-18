# qedis
Redis over QUIC with improved connection management


## Rationale

Curently, the official Redis client for Python, `redis-py` has many issues (ref: redis/redis-py#3008) regarding connection, retry, and timeout management.
Most problems are highlghy coupled to the API design, and it is hard to fix them without breaking the backward compatibility.
When it comes to HA configurations using Sentinels on top of `asyncio`, `redis-py` exhibits many buggy behaviors making it very difficult to distinguish the source of errors among multiple different stages of the connection setup process.

The target of this project is to:

* Offload the connection pool management to QUIC by adopting light-weight streams bound to local UNIX socket connections of the Redis server.
  - Let's transform Redis client connections to volatile, transient, and light-weight QUIC streams.
  - This splits the fault isolation domain of networking:
    1) the localhost of Redis server
    2) the QUIC remote networking to deal with intermittent packet loss and network instability
* Achieve potentially higher performance by eliminating handshake overheads when using secure TLS connections via public networks.
* Provide a working, ready-to-try client implementation for potential future QUIC adoption in the Redis project ([redis/redis#6301](https://github.com/redis/redis/issues/6301)).
* Suit the HA requirements when using Redis Sentinel in many of Lablup's customer sites.
  - Keep the event streams alive when a sentinel master failover happens, following [the full Sentinel clients specification](https://redis.io/docs/reference/sentinel-clients/).
  - Provide explicit logging and configurations for retries and give-up conditions.
  - Distinguish the errors during connection setup (e.g., `CLIENT INFO ...`) and the user-requested command failures.
* Make the codebase simple and clean by dropping considerations for non-async support and legacy Redis versions
  - Python 3.11+ (pattern matching, `asyncio.TaskGroup`, etc.)
  - Redis 6+ (though this library will minimize the command request/reply abstraction, removing high dependency to Redis versions)
    - Use RESP3 as the default protocol


## Development

### Editable installation

```sh
pip install -U -e '.[lint,typecheck,test,build,docs]'
```

### Building the reverse-proxy (QUIC to UNIX/TCP)

```sh
cd src/qedis-proxy
go build
```

### Testing

**Terminal 1:**
```sh
docker run -d -v /tmp:/tmp --name qedis-test redis:7-alpine \
  redis-server \
  --loglevel debug \
  --unixsocket /tmp/redis.sock \
  --unixsocketperm 777
```

**Terminal 2:**
```sh
cd src/qedis-proxy
./proxy -u unix -r /tmp/redis.sock  # proxy the local UDP 6379 port to the Redis
```

**Terminal 3:**
```sh
python examples/proof-of-concept.py -k  # use insecure option to allow self-signed cert
```
