import { memo } from "react";

interface LineChartProps {
  values: number[];
  labels?: string[];
  height?: number;
}

/**
 * Dependency-free responsive SVG line chart. Uses a fixed viewBox and scales to
 * its container width via CSS. Gracefully handles empty / single-point series.
 *
 * Memoized: parent panels re-render on every keystroke, while the chart's
 * props are identity-stable React Query arrays — memo skips rebuilding the
 * point strings and hundreds of SVG nodes until the data actually changes.
 */
function LineChart({ values, labels, height = 240 }: LineChartProps) {
  const width = 800;
  const padding = { top: 16, right: 16, bottom: 24, left: 48 };

  if (!values || values.length === 0) {
    return <div className="chart-empty">No price data to display.</div>;
  }

  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const stepX = values.length > 1 ? innerW / (values.length - 1) : 0;

  const x = (i: number) => padding.left + i * stepX;
  const y = (v: number) => padding.top + innerH - ((v - min) / range) * innerH;

  const linePoints = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const areaPoints =
    `${padding.left},${padding.top + innerH} ` +
    values.map((v, i) => `${x(i)},${y(v)}`).join(" ") +
    ` ${padding.left + (values.length - 1) * stepX},${padding.top + innerH}`;

  // Horizontal gridlines / y-axis ticks.
  const ticks = 4;
  const tickValues = Array.from({ length: ticks + 1 }, (_, i) => min + (range * i) / ticks);

  const lastIdx = values.length - 1;
  const lastVal = values[lastIdx] as number;

  const firstLabel = labels?.[0];
  const lastLabel = labels?.[lastIdx];

  return (
    <svg
      className="linechart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Price chart"
    >
      {tickValues.map((tv, i) => {
        const yy = y(tv);
        return (
          <g key={i}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yy}
              y2={yy}
              className="chart-grid"
            />
            <text x={padding.left - 8} y={yy + 4} className="chart-axis-label" textAnchor="end">
              {formatTick(tv)}
            </text>
          </g>
        );
      })}

      <polygon points={areaPoints} className="chart-area" />
      <polyline points={linePoints} className="chart-line" />

      {values.length > 1 && <circle cx={x(lastIdx)} cy={y(lastVal)} r={4} className="chart-dot" />}

      {firstLabel && (
        <text x={padding.left} y={height - 6} className="chart-axis-label" textAnchor="start">
          {firstLabel}
        </text>
      )}
      {lastLabel && (
        <text x={width - padding.right} y={height - 6} className="chart-axis-label" textAnchor="end">
          {lastLabel}
        </text>
      )}
    </svg>
  );
}

function formatTick(v: number): string {
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default memo(LineChart);
