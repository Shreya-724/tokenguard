import time
from tokenguard.bucket import TokenBucket

b = TokenBucket(capacity=10, refill_rate=1)
print([b.allow() for _ in range(10)])   # ten True
print(b.allow())                        # False
time.sleep(1.05)
print(b.allow(), b.allow())             # True False