-- Settle an estimate against real usage in a sliding-window log.
-- KEYS[1] = the key
-- ARGV[1] = limit
-- ARGV[2] = window length in seconds
-- ARGV[3] = delta (> 0 charge more, < 0 refund)
-- ARGV[4] = "now" override in seconds ('' = use Redis's own clock via TIME)
-- ARGV[5] = a unique id (used if an extra charge needs a new entry)
-- Returns the units left in the window, as a string.
-- A refund shrinks the NEWEST entries first (settling happens right after the
-- request that made them). An extra charge grows the newest entry. The total
-- stays within [0, 2 * limit], like the token bucket's bounded debt.
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

local live = redis.call('ZRANGEBYSCORE', KEYS[1],
                        '(' .. string.format('%.17g', now - window), '+inf', 'WITHSCORES')
local n = #live / 2
local members, scores, costs = {}, {}, {}
local used = 0
for i = 1, n do
  members[i] = live[2 * i - 1]
  scores[i]  = live[2 * i]                    -- keep the exact string
  costs[i]   = tonumber(string.match(members[i], ':([^:]*)$')) or 0
  used = used + costs[i]
end

local function id_of(member) return string.match(member, '^(.*):[^:]*$') end

if delta > 0 then
  local add = math.min(delta, math.max(0, 2 * limit - used))
  if add > 0 then
    if n > 0 then
      redis.call('ZREM', KEYS[1], members[n])
      redis.call('ZADD', KEYS[1], scores[n],
                 id_of(members[n]) .. ':' .. string.format('%.17g', costs[n] + add))
    else
      redis.call('ZADD', KEYS[1], string.format('%.17g', now),
                 ARGV[5] .. ':' .. string.format('%.17g', add))
    end
    redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000) + 1000)
    used = used + add
  end
elseif delta < 0 then
  local owed = -delta
  for i = n, 1, -1 do
    if owed <= 0 then break end
    local take = math.min(costs[i], owed)
    local left = costs[i] - take
    redis.call('ZREM', KEYS[1], members[i])
    if left > 1e-9 then
      redis.call('ZADD', KEYS[1], scores[i], id_of(members[i]) .. ':' .. string.format('%.17g', left))
    end
    used = used - take
    owed = owed - take
  end
end
return string.format('%.17g', limit - used)
