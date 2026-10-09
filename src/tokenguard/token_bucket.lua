-- KEYS[1] = bucket key
-- ARGV[1] = capacity
-- ARGV[2] = refill rate (tokens/sec)
-- ARGV[3] = cost
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = '1' to spend tokens, '0' to only peek
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local cost     = tonumber(ARGV[3])
local spend    = ARGV[5] == '1'

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
if tokens == nil or ts == nil then tokens = capacity; ts = now end

-- clock going backwards adds nothing
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)

local allowed = 0
local retry_after = 0
if cost <= tokens then
  allowed = 1
  if spend then tokens = tokens - cost end
elseif cost > capacity then
  retry_after = math.huge
else
  retry_after = (cost - tokens) / rate
end

if spend then
  -- %.17g keeps full float precision (redis would otherwise keep only 14 digits)
  redis.call('HSET', KEYS[1],
             'tokens', string.format('%.17g', tokens),
             'ts', string.format('%.17g', now))
  redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) * 2)
end

local retry_str = 'inf'
if retry_after ~= math.huge then retry_str = string.format('%.17g', retry_after) end
return {allowed, string.format('%.17g', tokens), retry_str}