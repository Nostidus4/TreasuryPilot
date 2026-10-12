import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { t } from '@/lib/i18n';

/**
 * Chart conventions (one place, so every chart reads the same):
 * one y-axis, 2px lines, rounded bar ends, recessive grid and axes, text in
 * text tokens (never the series colour), a tooltip on hover, and a table
 * view under every chart for screen readers and exact values.
 *
 * Amounts are plotted from display-unit numbers for geometry only; the exact
 * value shown in tooltips and tables is the pre-formatted `display` string.
 */
export interface ChartPoint {
  /** X-axis label, e.g. "Oct 12". */
  label: string;
  /** Plotted value in display units. */
  value: number;
  /** Exact, formatted value for the tooltip and the table. */
  display: string;
  note?: string;
}

export interface ChartReference {
  value: number;
  label: string;
}

const axisTick = { fill: 'hsl(var(--muted-foreground))', fontSize: 12 };
const gridStroke = 'hsl(var(--border))';

function ChartTooltip({
  active,
  payload,
  seriesLabel,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
  seriesLabel: string;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-surface px-2.5 py-1.5 shadow-float">
      <p className="text-xs text-muted-foreground">{point.label}</p>
      <p className="text-sm">
        <span className="text-muted-foreground">{seriesLabel}</span>{' '}
        <span className="num font-medium text-foreground">{point.display}</span>
      </p>
      {point.note && (
        <p className="text-xs text-muted-foreground">{point.note}</p>
      )}
    </div>
  );
}

function TableView({
  data,
  seriesLabel,
  xLabel,
}: {
  data: ChartPoint[];
  seriesLabel: string;
  xLabel: string;
}) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
        {t('View as table')}
      </summary>
      <table className="mt-2 w-full border-collapse">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th scope="col" className="py-1 font-medium">
              {xLabel}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {seriesLabel}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((point) => (
            <tr key={point.label} className="border-b last:border-0">
              <td className="py-1">{point.label}</td>
              <td className="num py-1 text-right">{point.display}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

interface SeriesChartProps {
  data: ChartPoint[];
  height?: number;
  references?: ChartReference[];
  /** What the single series is, e.g. "Projected balance". */
  seriesLabel: string;
  /** Accessible summary of what the chart shows. */
  summary: string;
  xLabel: string;
  yTickFormatter?: (value: number) => string;
}

const compact = (value: number) =>
  Math.abs(value) >= 1000
    ? `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`
    : String(value);

function References({ references }: { references?: ChartReference[] }) {
  return (
    <>
      {references?.map((reference) => (
        <ReferenceLine
          key={reference.label}
          y={reference.value}
          stroke="hsl(var(--muted-foreground))"
          strokeDasharray="4 4"
          label={{
            value: reference.label,
            position: 'insideBottomRight',
            fill: 'hsl(var(--muted-foreground))',
            fontSize: 12,
          }}
        />
      ))}
    </>
  );
}

export function LineSeriesChart({
  data,
  height = 220,
  references,
  seriesLabel,
  summary,
  xLabel,
  yTickFormatter = compact,
}: SeriesChartProps) {
  return (
    <figure>
      <div role="img" aria-label={summary} style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid stroke={gridStroke} vertical={false} />
            <XAxis
              dataKey="label"
              tick={axisTick}
              tickLine={false}
              axisLine={{ stroke: gridStroke }}
              minTickGap={24}
            />
            <YAxis
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={yTickFormatter}
            />
            <Tooltip
              cursor={{ stroke: 'hsl(var(--border-strong))' }}
              content={<ChartTooltip seriesLabel={seriesLabel} />}
            />
            {References({ references })}
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{
                r: 4,
                strokeWidth: 2,
                stroke: 'hsl(var(--surface))',
              }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView data={data} seriesLabel={seriesLabel} xLabel={xLabel} />
    </figure>
  );
}

export function BarSeriesChart({
  data,
  height = 220,
  references,
  seriesLabel,
  summary,
  xLabel,
  yTickFormatter = compact,
}: SeriesChartProps) {
  return (
    <figure>
      <div role="img" aria-label={summary} style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid stroke={gridStroke} vertical={false} />
            <XAxis
              dataKey="label"
              tick={axisTick}
              tickLine={false}
              axisLine={{ stroke: gridStroke }}
              minTickGap={16}
            />
            <YAxis
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={32}
              allowDecimals={false}
              tickFormatter={yTickFormatter}
            />
            <Tooltip
              cursor={{ fill: 'hsl(var(--surface-muted))' }}
              content={<ChartTooltip seriesLabel={seriesLabel} />}
            />
            {References({ references })}
            <Bar
              dataKey="value"
              fill="var(--chart-1)"
              radius={[4, 4, 0, 0]}
              maxBarSize={28}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView data={data} seriesLabel={seriesLabel} xLabel={xLabel} />
    </figure>
  );
}
