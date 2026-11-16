import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtClock } from "../lib/format.js";
import {
  labelSide as side,
  markerLabelPlacement,
  markerRows,
  niceMax,
  sliceWindow,
  timeTicks,
} from "../lib/series.js";
import { Empty } from "./States.jsx";

// Instrument styling: angular lines, no animation, horizontal gridlines only.
// BLOCKED is drawn last (on top) and more than twice as thick as ALLOWED, so
// token exhaustion jumps out of the baseline. The colours are mixes of the three
// brand colours (navy #14213D, cream #F4EDE0, coral #FF6B5B); Recharts needs
// plain values, so they are written out here: cream, coral, and cream at 14%,
// 62%, 74% over navy, and coral 55% of the way to cream.
export const COLORS = {
  allowed: "#F4EDE0",
  blocked: "#FF6B5B",
  grid: "#333E54",
  axis: "#9F9FA2",
  marker: "#BAB8B6",
  live: "#FAA697",
};
export const WIDTHS = { allowed: 1.25, blocked: 3 };
const MONO = '"Instrument Sans Variable", "Segoe UI", ui-sans-serif, system-ui, sans-serif';
const TICK = { fontSize: 10, fill: COLORS.axis, fontFamily: MONO };

export const WINDOWS = [
  { seconds: 60, label: "1M" },
  { seconds: 180, label: "3M" },
  { seconds: 600, label: "10M" },
];

// A rule-change label drawn by hand so it can sit on its own row. Recharts hands
// this the marker line's viewBox; markerLabelPlacement turns that into a position.
function MarkerLabel({ viewBox, value, side: where, row }) {
  if (!viewBox) return null;
  const { x, y, anchor } = markerLabelPlacement(viewBox, where, row);
  return (
    <text x={x} y={y} textAnchor={anchor} fill={COLORS.marker} fontSize={10} fontFamily={MONO}>
      {value}
    </text>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  return (
    <div className="tip">
      <div className="tip-time">{fmtClock(label)}</div>
      <div>
        <span className="swatch swatch-allowed" /> ALLOWED <b>{row.allowed}</b>
      </div>
      <div>
        <span className="swatch swatch-blocked" /> BLOCKED <b>{row.blocked}</b>
      </div>
    </div>
  );
}

export function TrafficChart({ history, windowSeconds, onWindowChange, markers }) {
  const data = useMemo(() => sliceWindow(history, windowSeconds), [history, windowSeconds]);
  const first = data[0]?.ts;
  const last = data[data.length - 1]?.ts;
  const ticks = useMemo(() => (first == null ? [] : timeTicks(first, last, 6)), [first, last]);
  const top = useMemo(() => niceMax(data), [data]);
  const rows = useMemo(
    () => (first == null ? {} : markerRows(markers, first, last)),
    [markers, first, last],
  );

  return (
    <div className="chart">
      <div className="chart-bar">
        <div className="legend">
          <span>
            <span className="swatch swatch-allowed" /> ALLOWED /s
          </span>
          <span>
            <span className="swatch swatch-blocked" /> BLOCKED /s
          </span>
          {markers.length > 0 && (
            <span>
              <span className="swatch swatch-marker" /> RULE CHANGE
            </span>
          )}
        </div>
        <div className="seg" role="group" aria-label="Chart window">
          {WINDOWS.map((w) => (
            <button
              key={w.seconds}
              type="button"
              className={`seg-btn${w.seconds === windowSeconds ? " is-on" : ""}`}
              aria-pressed={w.seconds === windowSeconds}
              onClick={() => onWindowChange(w.seconds)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>
      <div
        className="chart-body"
        role="img"
        aria-label={
          data.length
            ? `Requests per second, last ${windowSeconds} seconds. Latest: ${data[data.length - 1].allowed} allowed, ${data[data.length - 1].blocked} blocked.`
            : "Requests per second: no data yet"
        }
      >
        {data.length === 0 ? (
          <Empty label="NO DATA IN WINDOW" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 14, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={COLORS.grid} strokeDasharray="0" />
              <XAxis
                dataKey="ts"
                type="number"
                domain={[first, last]}
                ticks={ticks}
                tickFormatter={fmtClock}
                tick={TICK}
                tickLine={false}
                axisLine={{ stroke: COLORS.grid }}
                allowDataOverflow
              />
              <YAxis
                domain={[0, top]}
                allowDecimals={false}
                width={34}
                tick={TICK}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                content={<ChartTooltip />}
                cursor={{ stroke: COLORS.axis, strokeWidth: 1 }}
                isAnimationActive={false}
              />
              {markers.map((m) => (
                <ReferenceLine
                  key={`${m.id}-change`}
                  x={m.ts}
                  stroke={COLORS.marker}
                  strokeDasharray="2 3"
                  label={{
                    content: (props) => (
                      <MarkerLabel {...props} value={m.label} side={side(m.ts, first, last)} row={rows[m.id] ?? 0} />
                    ),
                  }}
                />
              ))}
              {markers.map((m) => (
                <ReferenceLine
                  key={`${m.id}-live`}
                  x={m.liveAt}
                  stroke={COLORS.live}
                  strokeDasharray="1 3"
                  label={{ value: "LIVE", position: `insideBottom${side(m.liveAt, first, last)}`, fill: COLORS.live, fontSize: 10, fontFamily: MONO }}
                />
              ))}
              <Line
                type="linear"
                dataKey="allowed"
                stroke={COLORS.allowed}
                strokeWidth={WIDTHS.allowed}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="blocked"
                stroke={COLORS.blocked}
                strokeWidth={WIDTHS.blocked}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
