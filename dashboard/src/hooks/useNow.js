import { useEffect, useState } from "react";

/** A clock that re-renders its component every `ms` (for ages and countdowns). */
export function useNow(ms = 500) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
