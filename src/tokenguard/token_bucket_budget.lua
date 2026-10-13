-- Charge the burst bucket AND the daily/monthly budgets in one atomic step.
-- Either every layer accepts the charge, or nothing at all is charged.
--
-- KEYS[1] = burst bucket hash        (fields: tokens, ts)
-- KEYS[2] = today's counters hash    (fields: tokens, usd)
-- KEYS[3] = this month's counters    (fields: tokens, usd)
-- ARGV[1] = capacity            ARGV[2] = refill rate (tokens/sec)
-- ARGV[3] = burst cost (weighted tokens)
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = raw tokens to add to the budgets   ARGV[6] = dollars to add
-- ARGV[7] = daily token limit     ARGV[8] = daily dollar limit
-- ARGV[9] = monthly token limit   ARGV[10] = monthly dollar limit   (0 = no limit)
-- ARGV[11] = day-counter TTL (seconds)   ARGV[12] = month-counter TTL (seconds)
--
-- Returns {allowed, blocked_by, burst_tokens, day_tokens, day_usd,
--          month_tokens, month_usd, burst_retry_after}, numbers as strings.
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local cost     = tonumber(ARGV[3])
local add_t    = tonumber(ARGV[5])
local add_u    = tonumber(ARGV[6])
local day_tl   = tonumber(ARGV[7])
local day_ul   = tonumber(ARGV[8])
local mon_tl   = tonumber(ARGV[9])
local mon_ul   = tonumber(ARGV[10])

local function fmt(x) return string.format('%.17g', x) end

local now
if ARGV[4] ~= nil and ARGV[4] ~= '' then
  now = tonumber(ARGV[4])
else
  local t = redis.call('TIME')
  now = tonumber(t[1]) + tonumber(t[2]) / 1000000
end

-- burst bucket: refilled, not yet charged
local data   = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])
if tokens == nil or ts == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)

-- budget counters so far (a missing field counts as 0)
local d = redis.call('HMGET', KEYS[2], 'tokens', 'usd')
local m = redis.call('HMGET', KEYS[3], 'tokens', 'usd')
local day_t = tonumber(d[1]) or 0
local day_u = tonumber(d[2]) or 0
local mon_t = tonumber(m[1]) or 0
local mon_u = tonumber(m[2]) or 0

-- Which layer says no? Longest-lived limit first, so retry_after is honest.
-- Dollar limits get a tiny tolerance so 0.6 + 0.4 still fits under 1.0.
local blocked = ''
if mon_tl > 0 and mon_t + add_t > mon_tl then
  blocked = 'monthly_tokens'
elseif mon_ul > 0 and mon_u + add_u > mon_ul + 1e-9 then
  blocked = 'monthly_usd'
elseif day_tl > 0 and day_t + add_t > day_tl then
  blocked = 'daily_tokens'
elseif day_ul > 0 and day_u + add_u > day_ul + 1e-9 then
  blocked = 'daily_usd'
elseif cost > tokens then
  blocked = 'burst'
end

local retry = 0
if blocked == '' then
  tokens = tokens - cost
  day_t = day_t + add_t
  day_u = day_u + add_u
  mon_t = mon_t + add_t
  mon_u = mon_u + add_u
  redis.call('HSET', KEYS[1], 'tokens', fmt(tokens), 'ts', fmt(now))
  redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) * 2)
  redis.call('HSET', KEYS[2], 'tokens', fmt(day_t), 'usd', fmt(day_u))
  redis.call('EXPIRE', KEYS[2], ARGV[11])
  redis.call('HSET', KEYS[3], 'tokens', fmt(mon_t), 'usd', fmt(mon_u))
  redis.call('EXPIRE', KEYS[3], ARGV[12])
elseif blocked == 'burst' then
  if cost > capacity then
    retry = math.huge
  else
    retry = (cost - tokens) / rate
  end
end

local retry_str = 'inf'
if retry ~= math.huge then retry_str = fmt(retry) end

local allowed = 0
if blocked == '' then allowed = 1 end
return {allowed, blocked, fmt(tokens), fmt(day_t), fmt(day_u),
        fmt(mon_t), fmt(mon_u), retry_str}
