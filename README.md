# qedis
Redis over QUIC with improved connection management


## Building the proxy

```sh
cd src/qedis-proxy
go build
```

## Testing

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
./proxy -u unix -r /tmp/redis.sock
```

**Terminal 3:**
```sh
python examples/proof-of-concept.py
```
