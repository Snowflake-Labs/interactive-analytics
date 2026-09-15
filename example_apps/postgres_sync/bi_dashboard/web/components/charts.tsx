'use client';

import { ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import { Granularity, Row, fmtDate, num } from '@/lib/cube';

/**
 * Thin wrappers over Recharts so the 32 tile definitions stay declarative.
 * Every chart takes Cube rows plus the fully-qualified member keys, and does its
 * own numeric coercion — Cube returns measures as strings.
 */

export const PALETTE = [
  '#29b5e8',
  '#11567f',
  '#71d3dc',
  '#f6b73c',
  '#e8734a',
  '#8a6bbe',
  '#5aab61',
  '#d45b8f',
  '#7c8da3',
  '#c9a227',
];

const AXIS = { stroke: '#8a94a6', fontSize: 11 };
const GRID = { stroke: '#e3e8ef', strokeDasharray: '3 3' };

function tip(v: unknown, fmt: (n: number) => string): string {
  return fmt(Number(v));
}

// --- time series -----------------------------------------------------------

export function TimeLine({
  rows,
  xKey,
  series,
  granularity,
  fmt,
}: {
  rows: Row[];
  xKey: string;
  series: Array<{ key: string; label: string }>;
  granularity: Granularity;
  fmt: (n: number) => string;
}) {
  const data = rows.map((r) => {
    const o: Record<string, string | number> = { x: fmtDate(r[xKey], granularity) };
    series.forEach((s) => (o[s.label] = num(r, s.key)));
    return o;
  });
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="x" {...AXIS} tickMargin={6} minTickGap={24} />
        <YAxis {...AXIS} tickFormatter={fmt} width={58} />
        <Tooltip formatter={(v) => tip(v, fmt)} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.label}
            stroke={PALETTE[i % PALETTE.length]}
            strokeWidth={1.8}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Long-format rows (x, series, value) pivoted into a stacked area. */
export function StackedArea({
  rows,
  xKey,
  seriesKey,
  valueKey,
  granularity,
  fmt,
}: {
  rows: Row[];
  xKey: string;
  seriesKey: string;
  valueKey: string;
  granularity: Granularity;
  fmt: (n: number) => string;
}) {
  const { data, keys } = pivot(rows, xKey, seriesKey, valueKey, granularity);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="x" {...AXIS} tickMargin={6} minTickGap={24} />
        <YAxis {...AXIS} tickFormatter={fmt} width={58} />
        <Tooltip formatter={(v) => tip(v, fmt)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {keys.map((k, i) => (
          <Area
            key={k}
            type="monotone"
            dataKey={k}
            stackId="1"
            stroke={PALETTE[i % PALETTE.length]}
            fill={PALETTE[i % PALETTE.length]}
            fillOpacity={0.75}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function StackedBars({
  rows,
  xKey,
  seriesKey,
  valueKey,
  fmt,
  granularity,
}: {
  rows: Row[];
  xKey: string;
  seriesKey: string;
  valueKey: string;
  fmt: (n: number) => string;
  /** Pass when xKey is a time dimension, or the axis prints raw ISO timestamps. */
  granularity?: Granularity;
}) {
  const { data, keys } = pivot(rows, xKey, seriesKey, valueKey, granularity);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="x" {...AXIS} tickMargin={6} interval={0} angle={-18} textAnchor="end" height={52} />
        <YAxis {...AXIS} tickFormatter={fmt} width={58} />
        <Tooltip formatter={(v) => tip(v, fmt)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} stackId="1" fill={PALETTE[i % PALETTE.length]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function pivot(
  rows: Row[],
  xKey: string,
  seriesKey: string,
  valueKey: string,
  granularity?: Granularity,
) {
  const byX = new Map<string, Record<string, string | number>>();
  const keys = new Set<string>();
  rows.forEach((r) => {
    const x = granularity ? fmtDate(r[xKey], granularity) : String(r[xKey] ?? '—');
    const s = String(r[seriesKey] ?? '—');
    keys.add(s);
    const bucket = byX.get(x) ?? { x };
    bucket[s] = num(r, valueKey);
    byX.set(x, bucket);
  });
  const keyList = [...keys].sort();
  // Recharts stacks treat undefined as a gap, so fill zeros explicitly.
  const data = [...byX.values()].map((d) => {
    keyList.forEach((k) => {
      if (d[k] === undefined) d[k] = 0;
    });
    return d;
  });
  return { data, keys: keyList };
}

// --- categorical -----------------------------------------------------------

export function Bars({
  rows,
  labelKey,
  valueKey,
  fmt,
  horizontal = false,
}: {
  rows: Row[];
  labelKey: string;
  valueKey: string;
  fmt: (n: number) => string;
  horizontal?: boolean;
}) {
  const data = rows.map((r) => ({ label: String(r[labelKey] ?? '—'), v: num(r, valueKey) }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout={horizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 6, right: 14, bottom: 0, left: horizontal ? 8 : 0 }}
      >
        <CartesianGrid {...GRID} />
        {/* These axes must be DIRECT children of BarChart. Recharts discovers
            axes by scanning its immediate children, so wrapping the pair in a
            <>...</> fragment hides them: vertical layout silently falls back to
            default axes, but horizontal layout collapses to a single
            mispositioned bar with no axes at all. */}
        {horizontal && <XAxis type="number" {...AXIS} tickFormatter={fmt} />}
        {horizontal && (
          <YAxis type="category" dataKey="label" {...AXIS} width={128} tickMargin={4} />
        )}
        {!horizontal && (
          <XAxis dataKey="label" {...AXIS} interval={0} angle={-20} textAnchor="end" height={62} />
        )}
        {!horizontal && <YAxis {...AXIS} tickFormatter={fmt} width={58} />}
        <Tooltip formatter={(v) => tip(v, fmt)} />
        <Bar dataKey="v" name="value" radius={horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Donut({
  rows,
  labelKey,
  valueKey,
  fmt,
}: {
  rows: Row[];
  labelKey: string;
  valueKey: string;
  fmt: (n: number) => string;
}) {
  const data = rows.map((r) => ({ name: String(r[labelKey] ?? '—'), value: num(r, valueKey) }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius="48%" outerRadius="76%">
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(v) => tip(v, fmt)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function Points({
  rows,
  labelKey,
  xKey,
  yKey,
  xFmt,
  yFmt,
  xLabel,
  yLabel,
}: {
  rows: Row[];
  labelKey: string;
  xKey: string;
  yKey: string;
  xFmt: (n: number) => string;
  yFmt: (n: number) => string;
  xLabel: string;
  yLabel: string;
}) {
  const data = rows.map((r) => ({
    name: String(r[labelKey] ?? '—'),
    x: num(r, xKey),
    y: num(r, yKey),
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart margin={{ top: 10, right: 14, bottom: 18, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis
          type="number"
          dataKey="x"
          {...AXIS}
          tickFormatter={xFmt}
          name={xLabel}
          label={{ value: xLabel, position: 'insideBottom', offset: -12, fontSize: 10 }}
        />
        <YAxis
          type="number"
          dataKey="y"
          {...AXIS}
          tickFormatter={yFmt}
          name={yLabel}
          width={58}
        />
        <ZAxis range={[60, 60]} />
        <Tooltip
          formatter={(v, n) => (n === 'x' ? xFmt(Number(v)) : yFmt(Number(v)))}
          labelFormatter={() => ''}
          content={({ payload }) => {
            const pt = payload?.[0]?.payload as { name: string; x: number; y: number } | undefined;
            if (!pt) return null;
            return (
              <div className="chart-tip">
                <strong>{pt.name}</strong>
                <div>
                  {xLabel}: {xFmt(pt.x)}
                </div>
                <div>
                  {yLabel}: {yFmt(pt.y)}
                </div>
              </div>
            );
          }}
        />
        <Scatter data={data} fill={PALETTE[0]} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// --- non-chart -------------------------------------------------------------

export function Kpi({
  value,
  sub,
}: {
  value: string;
  sub?: string;
}) {
  return (
    <div className="kpi">
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function DataTable({
  rows,
  columns,
}: {
  rows: Row[];
  columns: Array<{ key: string; label: string; fmt?: (n: number) => string; align?: 'left' | 'right' }>;
}) {
  return (
    <div className="table-scroll">
      <table className="dt">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{ textAlign: c.align ?? (c.fmt ? 'right' : 'left') }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} style={{ textAlign: c.align ?? (c.fmt ? 'right' : 'left') }}>
                  {c.fmt ? c.fmt(num(r, c.key)) : String(r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Center({ children }: { children: ReactNode }) {
  return <div className="center">{children}</div>;
}
