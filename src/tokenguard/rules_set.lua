-- Store or replace one live rule override and bump the rules version, atomically.
-- KEYS[1] = the rules hash
-- ARGV[1] = rule name
-- ARGV[2] = the override, as JSON
-- Returns the new version (a number that only ever goes up).
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
return redis.call('HINCRBY', KEYS[1], '__version__', 1)
