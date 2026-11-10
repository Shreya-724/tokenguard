import { useEffect, useRef, useState } from "react";
import { RULE, createScene } from "../lib/scene.js";

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/**
 * The animation (a token bucket guarding an API), with a button to send a burst
 * and the running totals as real text. The canvas is decoration: a screen reader
 * gets the sentence below it and the totals.
 */
export function HeroScene() {
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const [stats, setStats] = useState({ allowed: 0, blocked: 0, tokens: RULE.capacity });

  useEffect(() => {
    const scene = createScene(canvasRef.current, {
      animate: !reducedMotion(),
      onStats: setStats,
      fontFamily: getComputedStyle(document.body).getPropertyValue("--sans") || "sans-serif",
    });
    sceneRef.current = scene;
    return () => scene.destroy();
  }, []);

  return (
    <figure className="scene">
      <canvas ref={canvasRef} className="scene-canvas" aria-hidden="true" />
      <figcaption className="scene-caption">
        <p className="scene-rule">
          A bucket of {RULE.capacity} tokens, refilling {RULE.refillPerSecond} a second. Each request spends one.
          When the bucket is empty, the request gets a 429. This is a model running in your browser; the dashboard
          shows the real limiter.
        </p>
        <div className="scene-controls">
          <button type="button" className="h-btn h-btn-ghost" onClick={() => sceneRef.current?.send(12)}>
            Send 12 requests
          </button>
          <dl className="scene-stats" aria-label="Totals so far">
            <div>
              <dt>Allowed</dt>
              <dd>{stats.allowed}</dd>
            </div>
            <div>
              <dt>Blocked</dt>
              <dd className="is-blocked">{stats.blocked}</dd>
            </div>
            <div>
              <dt>Tokens left</dt>
              <dd>{stats.tokens.toFixed(1)}</dd>
            </div>
          </dl>
        </div>
      </figcaption>
    </figure>
  );
}
