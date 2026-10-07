import time
from tokenguard.bucket import TokenBucket

b = TokenBucket(capacity=10, refill_rate=1)
print([b.allow().allowed for _ in range(10)])   # ten True
print(not b.allow().allowed)                        # False
time.sleep(1.05)
print(b.allow().allowed, b.allow().allowed)             # True False