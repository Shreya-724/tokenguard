-- Settle an estimate against real usage in a fixed window.
-- KEYS[1] = the key
-- ARGV[1] = limit
-- ARGV[2] = window length in seconds
-- ARGV[3] = delta (> 0 charge more, < 0 refund)
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- Returns the units left in the current window, as a string.
-- The count stays within [0, 2 * limit]: refunds cannot go below zero and an
-- overspend is bounded, like the token bucket's debt. The change always lands
-- on the CURRENT window: a refund that arrives after the window rolled over
-- cannot be traced back to the old one (a known, small inaccuracy).
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local delta  = tonumber(ARGV[3])

local now
if ARGV[4] ~= nil and ARGV[4] ~= '' then
  now = tonumber(ARGV[4])
else
  local t = redis.call('TIME')
  now = tonumber(t[1]) + tonumber(t[2]) / 1000000
end

local idx = math.floor(now / window)
local data  = redis.call('HMGET', KEYS[1], 'count', 'idx')
local count = tonumber(data[1])
if count == nil or tonumber(data[2]) ~= idx then count = 0 end

local new = math.max(0, math.min(2 * limit, count + delta))
if new > 0 or count > 0 then
  redis.call('HSET', KEYS[1],
             'count', string.format('%.17g', new),
             'idx', string.format('%d', idx))
  redis.call('EXPIRE', KEYS[1], math.ceil(window) + 1)
end
return string.format('%.17g', limit - new)
