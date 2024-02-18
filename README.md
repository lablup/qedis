# qedis
Redis over QUIC with improved connection management


## Rationale

Curently, the official Redis client for Python, `redis-py` has many issues (ref: redis/redis-py#3008) regarding connection, retry, and timeout management.
Most problems are highlghy coupled to the API design, and it is hard to fix them without breaking the backward compatibility.
When it comes to HA configurations using sentinels on top of asyncio, `redis-py` exhibits many buggy behavior which makes it very difficult to distinguish the different stages of the connection setup process.

The target of this project is to:

* Offload the connection pool management to QUIC by adopting light-weight streams bound to local UNIX socket connections of the Redis server.
  - Make Redis client connections volatile, transient, light-weight QUIC streams.
  - Split the fault isolation domain of networking into the localhost of Redis server and the QUIC remote networking, instead of coupling them together as in the conventional TCP-based connection pooling.
* Achieve potentially higher performance by eliminating handshake overheads when using secure TLS connections via public networks.
* Provide a working, ready-to-try client implementation for potential future QUIC adoption in the Redis project ([redis/redis#6301](https://github.com/redis/redis/issues/6301)).
* Suit the HA requirements when using Redis Sentinel in many of Lablup's customer sites


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
