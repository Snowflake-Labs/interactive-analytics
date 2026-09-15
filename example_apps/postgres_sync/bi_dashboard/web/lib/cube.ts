/**
 * Typed Cube query helpers shared by every tile.
 *
 * Two things are centralised here so that a tile only declares its own measures
 * and dimensions:
 *
 *   1. Cube-name resolution. `db` ('pg' | 'sf') maps to the cube prefix, so a
 *      tile asks for `t('revenue')` and gets `PgTransactions.revenue` or
 *      `SfTransactions.revenue`.
 *   2. The global order_date range, injected into every query as a
 *      timeDimension so the time picker applies dashboard-wide.
 *
 * Queries always set renewQuery: true. Without it the second render of a tile
 * reports Cube's cache latency instead of the engine's, which would make the
 * whole pg-vs-sf comparison meaningless.
 */

export type Db = 'pg' | 'sf';

export type RangePreset = '1h' | '6h' | '1d' | '7d' | '30d' | '90d' | '1y' | 'all';

export const RANGE_PRESETS: RangePreset[] = [
  '1h',
  '6h',
  '1d',
  '7d',
  '30d',
  '90d',
  '1y',
  'all',
];

/**
 * The dashboard's range presets are anchored to the data's own end rather than
 * "now", so the demo keeps working as it ages. Set data_start / data_end /
 * data_end_ts in .env to your data's real bounds:
 *
 *   SELECT MIN(order_date), MAX(order_date) FROM <fact table>;
 *
 * DATA_END_TS matters for the sub-day presets: if the final day is only partly
 * populated, anchoring at midnight lands in an empty tail and every tile reads
 * "No rows in range". Use the true maximum.
 *
 * NEXT_PUBLIC_* is inlined at build time, so gen_env.py must have run before
 * `npm run build`. The fallbacks keep `npm run dev` usable without any env.
 */
export const DATA_START = process.env.NEXT_PUBLIC_DATA_START ?? '2024-09-12';
export const DATA_END = process.env.NEXT_PUBLIC_DATA_END ?? '2026-09-13';
export const DATA_END_TS = process.env.NEXT_PUBLIC_DATA_END_TS ?? `${DATA_END}T00:00:00`;

const DAYS: Record<'1d' | '7d' | '30d' | '90d' | '1y', number> = {
  '1d': 1,
  '7d': 7,
  '30d': 30,
  '90d': 90,
  '1y': 365,
};

const HOURS: Record<'1h' | '6h', number> = {
  '1h': 1,
  '6h': 6,
};

function isHourPreset(p: RangePreset): p is '1h' | '6h' {
  return p === '1h' || p === '6h';
}

/** Cube accepts ISO datetimes in dateRange, which the sub-day presets need. */
function isoMinutes(d: Date): string {
  return d.toISOString().slice(0, 19);
}

export function rangeToDates(preset: RangePreset): [string, string] {
  if (preset === 'all') return [DATA_START, DATA_END];

  if (isHourPreset(preset)) {
    const end = new Date(`${DATA_END_TS}Z`);
    const start = new Date(end);
    start.setUTCHours(start.getUTCHours() - HOURS[preset]);
    return [isoMinutes(start), isoMinutes(end)];
  }

  const end = new Date(`${DATA_END}T00:00:00Z`);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - DAYS[preset]);
  return [start.toISOString().slice(0, 10), DATA_END];
}

// --- cube name resolution --------------------------------------------------

const PREFIX: Record<Db, string> = { pg: 'Pg', sf: 'Sf' };

export function transactionsCube(db: Db): string {
  return `${PREFIX[db]}Transactions`;
}
export function productsCube(db: Db): string {
  return `${PREFIX[db]}Products`;
}
export function usersCube(db: Db): string {
  return `${PREFIX[db]}Users`;
}

/** Member on the fact cube, e.g. t('sf', 'revenue') -> 'SfTransactions.revenue'. */
export function t(db: Db, member: string): string {
  return `${transactionsCube(db)}.${member}`;
}
export function p(db: Db, member: string): string {
  return `${productsCube(db)}.${member}`;
}
export function u(db: Db, member: string): string {
  return `${usersCube(db)}.${member}`;
}

// --- query construction ----------------------------------------------------

export type Granularity = 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter';

export interface TileQuerySpec {
  measures?: string[];
  dimensions?: string[];
  /** Granularity for the injected order_date time dimension, if the tile is a trend. */
  granularity?: Granularity;
  /**
   * Additional time dimensions with their own granularity but no date range --
   * used by the cohort heatmap, which needs signup_date bucketed by month as a
   * second axis alongside the global order_date range.
   */
  extraTimeDimensions?: Array<{ dimension: string; granularity: Granularity }>;
  filters?: CubeFilter[];
  order?: Record<string, 'asc' | 'desc'>;
  limit?: number;
}

export interface CubeFilter {
  member: string;
  operator: string;
  values?: string[];
}

export interface CubeQuery {
  measures?: string[];
  dimensions?: string[];
  timeDimensions: Array<{
    dimension: string;
    dateRange?: [string, string];
    granularity?: Granularity;
  }>;
  filters?: CubeFilter[];
  order?: Record<string, 'asc' | 'desc'>;
  limit?: number;
  renewQuery: boolean;
  timezone: string;
}

/**
 * Makes every request unique so Cube's result cache can never match it.
 *
 * Cube Core has no option to disable the query result cache. `renewQuery: true`,
 * a volatile per-cube `refresh_key` (SELECT random()),
 * `orchestratorOptions.queryCacheOptions.refreshKeyRenewalThreshold: 0` and
 * `skipExternalCacheAndQueue: true` were all measured and none of them worked:
 * four identical requests still produced exactly one SQL execution against
 * Snowflake, with the repeats answered in ~0.08s. Since the demo's whole purpose
 * is to compare engine latency, a cached repeat is worse than useless.
 *
 * The nonce rides on the fact table's primary key as an always-true predicate
 * (`transaction_id > <negative>`), which is the cheapest way to reach the
 * generated SQL — Cube's cache key is derived from the SQL and its params, so a
 * change confined to the request JSON would not be enough. Both sources get the
 * identical predicate, so the comparison stays fair: Snowflake resolves it from
 * partition metadata and Postgres applies it as a trivial filter on rows it is
 * already reading.
 *
 * Remove this (and `renewQuery`) if the dashboard is ever used for anything other
 * than the comparison — it deliberately defeats caching that a real deployment
 * would want.
 */
let nonce = 0;

function cacheBuster(db: Db): CubeFilter {
  nonce += 1;
  return {
    member: t(db, 'transactionId'),
    operator: 'gt',
    values: [String(-(Date.now() % 1_000_000_000) - nonce)],
  };
}

export function buildQuery(db: Db, range: RangePreset, spec: TileQuerySpec): CubeQuery {
  return {
    measures: spec.measures,
    dimensions: spec.dimensions,
    timeDimensions: [
      {
        dimension: t(db, 'orderDate'),
        dateRange: rangeToDates(range),
        ...(spec.granularity ? { granularity: spec.granularity } : {}),
      },
      ...(spec.extraTimeDimensions ?? []),
    ],
    filters: [...(spec.filters ?? []), cacheBuster(db)],
    ...(spec.order ? { order: spec.order } : {}),
    ...(spec.limit ? { limit: spec.limit } : {}),
    renewQuery: true,
    timezone: 'UTC',
  };
}

// --- execution -------------------------------------------------------------

export type Row = Record<string, string | number | null>;

export interface QueryResult {
  data: Row[];
  /** Wall-clock milliseconds for the whole round trip, shown on the tile badge. */
  latencyMs: number;
}

/**
 * Runs a query through the app's own /api/cube proxy, which holds the Cube API
 * secret server-side. Errors are surfaced as thrown Errors for the tile's error
 * boundary to render.
 */
export async function runQuery(query: CubeQuery, signal?: AbortSignal): Promise<QueryResult> {
  const started = performance.now();
  const res = await fetch('/api/cube/load', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query }),
    signal,
  });
  const latencyMs = Math.round(performance.now() - started);

  const payload = (await res
    .json()
    .catch(() => ({ error: `Non-JSON response (${res.status})` }))) as {
    data?: Row[];
    error?: string;
  };
  if (!res.ok || payload.error) {
    throw new Error(payload.error ?? `Cube returned ${res.status}`);
  }
  return { data: payload.data ?? [], latencyMs };
}

// --- formatting ------------------------------------------------------------

export function num(row: Row, key: string): number {
  const v = row?.[key];
  if (v === null || v === undefined) return 0;
  return typeof v === 'number' ? v : Number(v);
}

export function fmtCurrency(v: number): string {
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(2)}`;
}

export function fmtCount(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString();
}

export function fmtPct(v: number): string {
  return `${v.toFixed(1)}%`;
}

/** Trims Cube's ISO timestamps to something readable on an axis. */
export function fmtDate(v: string | number | null, granularity: Granularity): string {
  if (!v) return '';
  const s = String(v);
  if (granularity === 'month' || granularity === 'quarter') return s.slice(0, 7);
  // A minute-grained axis only ever spans one hour, so the date is redundant.
  if (granularity === 'minute') return s.slice(11, 16);
  // The 1d range's inclusive end date pulls in the first hour of the next day, so
  // an hour-only label would print 00:00 twice. Keep MM-DD.
  if (granularity === 'hour') return `${s.slice(5, 10)} ${s.slice(11, 13)}h`;
  return s.slice(0, 10);
}
