import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
print("ping:", r.ping())
r.hset("tb:smoke", mapping={"tokens": 10, "ts": 1700000000.5})
r.expire("tb:smoke", 30)
print("hash:", r.hgetall("tb:smoke"), "ttl:", r.ttl("tb:smoke"))
r.delete("tb:smoke")
