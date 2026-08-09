import type { ReplayFire } from "../api/types";

interface ReplayChartProps {
  closes: number[];
  dates: string[];
  fires: ReplayFire[];
  height?: number;
}

/**
 * The signal-replay timeline: the price path with a marker at every bar where
 * the condition would have fired. Same dependency-free SVG approach as
 * LineChart, plus the fire overlay.
 */
export default function ReplayChart({ closes, dates, fires, height = 220 }: ReplayChartProps) {
  const width = 800;
  const padding = { top: 16, right: 16, bottom: 24, left: 48 };

  if (!closes || closes.length === 0) {
    return <div className="chart-empty">No bars to display.</div>;
  }

  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const stepX = closes.length > 1 ? innerW / (closes.length - 1) : 0;
  const x = (i: number) => padding.left + i * stepX;
  const y = (v: number) => padding.top + innerH - ((v - min) / range) * innerH;

  const linePoints = closes.map((v, i) => `${x(i)},${y(v)}`).join(" ");

  const ticks = 4;
  const tickValues = Array.from({ length: ticks + 1 }, (_, i) => min + (range * i) / ticks);

  const validFires = fires.filter((f) => f.index >= 0 && f.index < closes.length);

  return (
    <svg
      className="linechart replaychart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Replay chart: condition fired ${validFires.length} times`}
    >
      {tickValues.map((tv, i) => (
        <g key={i}>
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={y(tv)}
            y2={y(tv)}
            className="chart-grid"
          />
          <text x={padding.left - 8} y={y(tv) + 4} className="chart-axis-label" textAnchor="end">
            {tv >= 1000
              ? tv.toLocaleString(undefined, { maximumFractionDigits: 0 })
              : tv.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </text>
        </g>
      ))}

      <polyline points={linePoints} className="chart-line" />

      {validFires.map((f) => (
        <g key={f.index} className="replay-fire-marker">
          <line
            x1={x(f.index)}
            x2={x(f.index)}
            y1={padding.top}
            y2={padding.top + innerH}
            className="replay-fire-line"
          />
          <circle cx={x(f.index)} cy={y(closes[f.index] as number)} r={4} className="replay-fire-dot">
            <title>
              {(f.date ? f.date.slice(0, 10) : `bar ${f.index}`) +
                (f.metric != null ? ` · metric ${f.metric.toFixed(4)}` : "")}
            </title>
          </circle>
        </g>
      ))}

      {dates[0] && (
        <text x={padding.left} y={height - 6} className="chart-axis-label" textAnchor="start">
          {dates[0].slice(0, 10)}
        </text>
      )}
      {dates[dates.length - 1] && (
        <text x={width - padding.right} y={height - 6} className="chart-axis-label" textAnchor="end">
          {(dates[dates.length - 1] as string).slice(0, 10)}
        </text>
      )}
    </svg>
  );
}
