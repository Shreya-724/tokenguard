-- Sliding-window LOG: at most `limit` units in ANY span of `window` seconds.
-- A sorted set holds one entry per spending request: score = when it happened,
-- member = "<request id>:<cost>". Costs are summed over the live entries, so one
-- 5,000-token request is one entry, not 5,000.
-- KEYS[1] = the key
-- ARGV[1] = limit
-- ARGV[2] = window length in seconds
-- ARGV[3] = cost
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = '1' to spend, '0' to only peek
-- ARGV[6] = a unique id for this request (members must be unique)
-- Returns {allowed, remaining, retry_after, reset_after}; numbers as strings.
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local cost   = tonumber(ARGV[3])
local spend  = ARGV[5] == '1'

local now
if ARGV[4] ~= nil and ARGV[4] ~= '' then
  now = tonumber(ARGV[4])
else
  local t = redis.call('TIME')
  now = tonumber(t[1]) + tonumber(t[2]) / 1000000
end

-- The window is (now - window, now]: an entry exactly `window` old is free again.
local cutoff = now - window
local live = redis.call('ZRANGEBYSCORE', KEYS[1],
                        '(' .. string.format('%.17g', cutoff), '+inf', 'WITHSCORES')
local n = #live / 2
local scores, costs = {}, {}
local used = 0
for i = 1, n do
  scores[i] = tonumber(live[2 * i])
  costs[i]  = tonumber(string.match(live[2 * i - 1], ':([^:]*)$')) or 0
  used = used + costs[i]
end

local allowed = 0
local retry_after = 0
-- 1e-9 of slack so fractional costs do not fail on float rounding
if used + cost <= limit + 1e-9 then
  allowed = 1
  if spend and cost > 0 then
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)   -- drop expired entries
    redis.call('ZADD', KEYS[1], string.format('%.17g', now),
               ARGV[6] .. ':' .. string.format('%.17g', cost))
    redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000) + 1000)
    n = n + 1
    scores[n] = now
    costs[n] = cost
    used = used + cost
  end
elseif cost > limit then
  retry_after = math.huge                     -- can never fit
else
  -- Walk the entries oldest first: when enough of them have expired, it fits.
  local freed = 0
  for i = 1, n do
    freed = freed + costs[i]
    if used - freed + cost <= limit + 1e-9 then
      retry_after = scores[i] + window - now
      break
    end
  end
end

local reset_after = 0                         -- when the last entry expires
if n > 0 then reset_after = scores[n] + window - now end

local function num(x)
  if x == math.huge then return 'inf' end
  return string.format('%.17g', x)
end
return {allowed, num(limit - used), num(retry_after), num(reset_after)}
