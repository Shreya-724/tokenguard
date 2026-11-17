/**
 * Which bucket the "Bucket level" panel should watch.
 *
 * While `auto` is on (nobody has picked a key yet), follow the top consumer so
 * the panel is never empty during a run. It sticks with its current key for as
 * long as that key is still on the consumers list, so the gauge does not jump
 * around when the ranking changes; it moves only when that key drops off the list.
 * Once the user picks or types a key, `auto` is off and their key is left alone.
 *
 * @param {string|null} current  the key being watched now
 * @param {boolean} auto         true until the user chooses a key
 * @param {{key: string}[]|undefined} consumers  top consumers, biggest first
 */
export function autoWatchKey(current, auto, consumers) {
  if (!auto || !consumers || consumers.length === 0) return current;
  if (current && consumers.some((c) => c.key === current)) return current;
  return consumers[0].key;
}
