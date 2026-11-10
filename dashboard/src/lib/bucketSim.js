// A token bucket small enough to run in a browser tab: the home page animation
// uses it. The rule is the same one the server applies: the bucket holds at most
// `capacity` tokens, refills at `refillPerSecond`, and a request is allowed only
// if it can pay its cost in full.

export function createBucket(capacity, refillPerSecond) {
  if (!(capacity > 0) || !(refillPerSecond > 0)) {
    throw new RangeError("capacity and refillPerSecond must be above 0");
  }
  return { capacity, refillPerSecond, tokens: capacity };
}

/** Let `seconds` pass. Never goes above capacity. */
export function advance(bucket, seconds) {
  if (seconds > 0) {
    bucket.tokens = Math.min(bucket.capacity, bucket.tokens + seconds * bucket.refillPerSecond);
  }
  return bucket;
}

/** Spend `cost` tokens if there are enough. Returns true when the request is allowed. */
export function take(bucket, cost = 1) {
  if (bucket.tokens + 1e-9 < cost) return false;
  bucket.tokens = Math.max(0, bucket.tokens - cost);
  return true;
}

/** Seconds until `cost` tokens are available (0 if they already are). */
export function retryAfter(bucket, cost = 1) {
  const missing = cost - bucket.tokens;
  return missing <= 0 ? 0 : missing / bucket.refillPerSecond;
}
