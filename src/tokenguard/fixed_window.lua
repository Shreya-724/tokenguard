-- Fixed-window counter: at most `limit` units per window of `window` seconds.
-- One hash per key: count (units used) and idx (which window the count is for).
-- KEYS[1] = the key
-- ARGV[1] = limit
-- ARGV[2] = window length in seconds
-- ARGV[3] = cost
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = '1' to spend, '0' to only peek
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

local idx = math.floor(now / window)           -- which window we are in
local window_end = (idx + 1) * window

local data  = redis.call('HMGET', KEYS[1], 'count', 'idx')
local count = tonumber(data[1])
if count == nil or tonumber(data[2]) ~= idx then count = 0 end  -- new window

local allowed = 0
local retry_after = 0
-- 1e-9 of slack so fractional costs do not fail on float rounding
if count + cost <= limit + 1e-9 then
  allowed = 1
  if spend and cost > 0 then
    count = count + cost
    redis.call('HSET', KEYS[1],
               'count', string.format('%.17g', count),
               'idx', string.format('%d', idx))
    redis.call('EXPIRE', KEYS[1], math.ceil(window) + 1)
  end
elseif cost > limit then
  retry_after = math.huge                         -- can never fit in one window
else
  retry_after = window_end - now
end

local function num(x)
  if x == math.huge then return 'inf' end
  return string.format('%.17g', x)
end
return {allowed, num(limit - count), num(retry_after), num(window_end - now)}
