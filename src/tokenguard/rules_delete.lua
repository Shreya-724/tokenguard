-- Remove one live rule override and bump the rules version, atomically.
-- KEYS[1] = the rules hash
-- ARGV[1] = rule name
-- Returns the new version, or -1 if there was no such override (nothing changes).
if redis.call('HDEL', KEYS[1], ARGV[1]) == 1 then
  return redis.call('HINCRBY', KEYS[1], '__version__', 1)
end
return -1
