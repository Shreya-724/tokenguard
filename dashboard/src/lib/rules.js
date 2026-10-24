// The rule editor's form logic: parse what was typed, and describe what changed.

export const ALGORITHMS = ["token_bucket", "fixed_window", "sliding_window"];

/** The three form fields (as strings) for a rule's current effective values. */
export function formFromRule(rule) {
  const e = rule.effective;
  return {
    capacity: String(e.capacity),
    refill_rate: String(e.refill_rate),
    algorithm: e.algorithm,
  };
}

function positive(label, text, errors) {
  const raw = String(text ?? "").trim();
  if (raw === "") {
    errors[label] = "required";
    return undefined;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) {
    errors[label] = "must be a number above 0";
    return undefined;
  }
  return n;
}

/**
 * Check the form. Returns { ok, body, errors }; `body` is what the API wants.
 * `rule` is the rule being edited (a budgeted rule only takes the token bucket).
 */
export function parseRuleForm(form, rule) {
  const errors = {};
  const capacity = positive("capacity", form.capacity, errors);
  const refill_rate = positive("refill_rate", form.refill_rate, errors);
  const algorithm = form.algorithm;
  if (!ALGORITHMS.includes(algorithm)) {
    errors.algorithm = "unknown algorithm";
  } else if (rule?.budget && algorithm !== "token_bucket") {
    errors.algorithm = "a rule with a budget must use token_bucket";
  }
  const ok = Object.keys(errors).length === 0;
  return { ok, body: ok ? { capacity, refill_rate, algorithm } : null, errors };
}

/** "capacity 60→100 · refill/s 1→5": only what differs, for the chart marker. */
export function describeChange(effective, body) {
  const parts = [];
  if (body.capacity !== effective.capacity) {
    parts.push(`capacity ${effective.capacity}→${body.capacity}`);
  }
  if (body.refill_rate !== effective.refill_rate) {
    parts.push(`refill/s ${effective.refill_rate}→${body.refill_rate}`);
  }
  if (body.algorithm !== effective.algorithm) {
    parts.push(`${effective.algorithm}→${body.algorithm}`);
  }
  return parts.length ? parts.join(" · ") : "no change";
}

export function isChange(effective, body) {
  return describeChange(effective, body) !== "no change";
}
