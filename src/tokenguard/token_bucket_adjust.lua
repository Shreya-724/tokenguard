-- Settle an estimate against real usage.
-- KEYS[1] = bucket key
-- ARGV[1] = capacity
-- ARGV[2] = refill rate (tokens/sec)
-- ARGV[3] = delta: tokens to charge (positive) or refund (negative)
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- Returns the new token balance as a string.
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local delta    = tonumber(ARGV[3])

local now
if ARGV[4] ~= nil and ARGV[4] ~= '' then
  now = tonumber(ARGV[4])
else
  local t = redis.call('TIME')
  now = tonumber(t[1]) + tonumber(t[2]) / 1000000
end

local data   = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])
-- the bucket may have expired while the request ran: assume it is full
if tokens == nil or ts == nil then tokens = capacity; ts = now end

-- refill first so the adjustment applies to an up-to-date balance
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)

-- debt is allowed but bounded: never below -capacity, never above capacity
tokens = math.max(-capacity, math.min(capacity, tokens - delta))

redis.call('HSET', KEYS[1],
           'tokens', string.format('%.17g', tokens),
           'ts', string.format('%.17g', now))
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) * 2)
return string.format('%.17g', tokens)
