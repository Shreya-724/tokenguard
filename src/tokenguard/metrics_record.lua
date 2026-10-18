-- Record one decision (or one correction) in a single atomic call.
-- KEYS[1] = this minute's hash   (per-second and per-rule counters)
-- KEYS[2] = this minute's top-consumers sorted set   (score = tokens spent)
-- KEYS[3] = this minute's blocked sorted set         (score = blocked requests)
-- ARGV[1] = second within the minute (0-59)
-- ARGV[2] = rule scope
-- ARGV[3] = consumer ("scope" 0x1f "identity")
-- ARGV[4] = allowed requests to add (0 or 1)
-- ARGV[5] = blocked requests to add (0 or 1)
-- ARGV[6] = tokens to add (may be negative: a correction after reconcile)
-- ARGV[7] = seconds to keep the keys
-- ARGV[8] = most consumers kept per minute (the rest are the smallest)
local sec, scope, member = ARGV[1], ARGV[2], ARGV[3]
local allowed, blocked = tonumber(ARGV[4]), tonumber(ARGV[5])
local tokens = tonumber(ARGV[6])
local ttl, cap = tonumber(ARGV[7]), tonumber(ARGV[8])

if allowed ~= 0 then
  redis.call('HINCRBY', KEYS[1], sec .. ':a', allowed)
  redis.call('HINCRBY', KEYS[1], 'r:' .. scope .. ':a', allowed)
end
if blocked ~= 0 then
  redis.call('HINCRBY', KEYS[1], sec .. ':b', blocked)
  redis.call('HINCRBY', KEYS[1], 'r:' .. scope .. ':b', blocked)
  redis.call('ZINCRBY', KEYS[3], blocked, member)
  redis.call('EXPIRE', KEYS[3], ttl)
  if redis.call('ZCARD', KEYS[3]) > cap then
    redis.call('ZREMRANGEBYRANK', KEYS[3], 0, 0)
  end
end
if tokens ~= 0 then
  redis.call('HINCRBYFLOAT', KEYS[1], sec .. ':t', tokens)
  redis.call('HINCRBYFLOAT', KEYS[1], 'r:' .. scope .. ':t', tokens)
  redis.call('ZINCRBY', KEYS[2], tokens, member)
  redis.call('EXPIRE', KEYS[2], ttl)
  if redis.call('ZCARD', KEYS[2]) > cap then
    redis.call('ZREMRANGEBYRANK', KEYS[2], 0, 0)
  end
end
redis.call('EXPIRE', KEYS[1], ttl)
return 1
