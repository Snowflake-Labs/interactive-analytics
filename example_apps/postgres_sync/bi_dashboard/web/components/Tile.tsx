'use client';

import { ReactNode, useEffect, useRef, useState } from 'react';
import {
  CubeQuery,
  Db,
  QueryResult,
  RangePreset,
  Row,
  TileQuerySpec,
  buildQuery,
  runQuery,
} from '@/lib/cube';

/**
 * Per-tile data fetching, isolated so a single slow or failing tile cannot blank
 * the dashboard. Each tile owns its own loading, error, and latency state.
 *
 * The latency badge is the point of the whole dashboard: it reports wall-clock
 * round-trip time per tile, so switching the DB picker makes the Postgres vs
 * Snowflake-interactive difference visible tile by tile.
 */

export interface TileProps {
  n: number;
  title: string;
  db: Db;
  range: RangePreset;
  spec: TileQuerySpec;
  /** Rendered once data has arrived. */
  children: (rows: Row[]) => ReactNode;
  /** Grid column span; defaults to 1. */
  span?: number;
  height?: number;
}

export function Tile({ n, title, db, range, spec, children, span = 1, height = 240 }: TileProps) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Re-query whenever the DB or time range changes. The spec is stable per tile,
  // so it is serialised into the dep key rather than compared by reference.
  const specKey = JSON.stringify(spec);

  useEffect(() => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;

    // Distinguishing a timeout abort from a supersede abort cannot rely on
    // inspecting signal.reason: an argument-less abort() produces a DOMException,
    // and `DOMException instanceof Error` is true in V8, so the two are
    // indistinguishable by type. An explicit flag is the only reliable signal.
    let timedOut = false;

    // Bound each tile's own wall clock. The server-side proxy already gives up at
    // 75s, but with 32 tiles issuing concurrent long-lived POSTs the proxy's
    // fetch to Cube can sit waiting for a free socket in the per-origin pool, so
    // a tile's 75s can start minutes after it was dispatched. This makes the
    // deadline the tile's, not the socket's.
    const timer = setTimeout(() => {
      timedOut = true;
      ac.abort();
    }, 90_000);

    setResult(null);
    setError(null);

    const query: CubeQuery = buildQuery(db, range, JSON.parse(specKey) as TileQuerySpec);
    runQuery(query, ac.signal)
      .then((r) => {
        if (!ac.signal.aborted) setResult(r);
      })
      .catch((e: unknown) => {
        if (timedOut) {
          setError('Tile timed out after 90s.');
          return;
        }
        // A supersede abort (db or range changed) must stay silent: the effect has
        // already re-run and a fresh request is in flight.
        if (ac.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [db, range, specKey]);

  return (
    <section className="tile" style={{ gridColumn: `span ${span}` }}>
      <header className="tile-head">
        <h3>
          <span className="tile-n">{n}</span>
          {title}
        </h3>
        <LatencyBadge latencyMs={result?.latencyMs} error={!!error} db={db} />
      </header>
      <div className="tile-body" style={{ height }}>
        {error ? (
          <div className="tile-error">
            <strong>Query failed</strong>
            <p>{error}</p>
          </div>
        ) : !result ? (
          <div className="tile-loading">
            <div className="spinner" />
          </div>
        ) : result.data.length === 0 ? (
          <div className="tile-empty">No rows in range</div>
        ) : (
          children(result.data)
        )}
      </div>
    </section>
  );
}

function LatencyBadge({
  latencyMs,
  error,
  db,
}: {
  latencyMs?: number;
  error: boolean;
  db: Db;
}) {
  if (error) return <span className="badge badge-err">error</span>;
  if (latencyMs === undefined) return <span className="badge badge-wait">…</span>;
  // 5s is the interactive warehouse's hard timeout; past that a query has been
  // silently retried on the ADAPTIVE fallback, which is worth seeing.
  const tier = latencyMs < 1000 ? 'fast' : latencyMs < 5000 ? 'ok' : 'slow';
  return (
    <span className={`badge badge-${tier}`} title={`${db} · ${latencyMs}ms round trip`}>
      {latencyMs < 1000 ? `${latencyMs}ms` : `${(latencyMs / 1000).toFixed(1)}s`}
    </span>
  );
}
