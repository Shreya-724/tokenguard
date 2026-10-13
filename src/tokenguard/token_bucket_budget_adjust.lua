-- Settle an estimate against real usage for the burst bucket AND both budgets,
-- atomically, so a refund never lands in one layer but not another.
--
-- KEYS[1] = burst bucket hash   KEYS[2] = day counters   KEYS[3] = month counters
-- ARGV[1] = capacity            ARGV[2] = refill rate (tokens/sec)
-- ARGV[3] = burst delta (weighted tokens; positive charges, negative refunds)
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = budget token delta  ARGV[6] = budget dollar delta
-- ARGV[7] = day-counter TTL     ARGV[8] = month-counter TTL
--
-- Returns {burst_tokens, day_tokens, day_usd, month_tokens, month_usd} as strings.
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local delta    = tonumber(ARGV[3])
local dt       = tonumber(ARGV[5])
local du       = tonumber(ARGV[6])

local function fmt(x) return string.format('%.17g', x) end

local now
if ARGV[4] ~= nil and ARGV[4] ~= '' then
  now = tonumber(ARGV[4])
else
  local t = redis.call('TIME')
  now = tonumber(t[1]) + tonumber(t[2]) / 1000000
end

-- burst bucket: refill, then apply the delta (bounded debt, as in the plain adjust)
local data   = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])
if tokens == nil or ts == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
tokens = math.max(-capacity, math.min(capacity, tokens - delta))
redis.call('HSET', KEYS[1], 'tokens', fmt(tokens), 'ts', fmt(now))
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) * 2)

-- budget counters: apply the delta, but spend can never go below zero
local function bump(key, ttl)
  local v = redis.call('HMGET', key, 'tokens', 'usd')
  local t = math.max(0, (tonumber(v[1]) or 0) + dt)
  local u = math.max(0, (tonumber(v[2]) or 0) + du)
  redis.call('HSET', key, 'tokens', fmt(t), 'usd', fmt(u))
  redis.call('EXPIRE', key, ttl)
  return t, u
end
local day_t, day_u = bump(KEYS[2], ARGV[7])
local mon_t, mon_u = bump(KEYS[3], ARGV[8])

return {fmt(tokens), fmt(day_t), fmt(day_u), fmt(mon_t), fmt(mon_u)}
