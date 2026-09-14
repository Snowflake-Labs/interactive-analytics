'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Db, RANGE_PRESETS, RangePreset, rangeToDates } from '@/lib/cube';

/**
 * Dashboard-wide filters. Both live in URL search params so a specific
 * comparison (say, sf at 1y) is a shareable link.
 */
export function Filters({ db, range }: { db: Db; range: RangePreset }) {
  const router = useRouter();
  const params = useSearchParams();

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    next.set(key, value);
    router.replace(`?${next.toString()}`, { scroll: false });
  };

  const [from, to] = rangeToDates(range);

  return (
    <div className="filters">
      <div className="filter-group">
        <span className="filter-label">Source</span>
        <div className="segmented">
          <button
            className={db === 'sf' ? 'on' : ''}
            onClick={() => set('db', 'sf')}
            title="Snowflake, served through the interactive warehouse"
          >
            Snowflake
          </button>
          <button
            className={db === 'pg' ? 'on' : ''}
            onClick={() => set('db', 'pg')}
            title="Postgres, queried directly"
          >
            Postgres
          </button>
        </div>
      </div>

      <div className="filter-group">
        <span className="filter-label">Range</span>
        <div className="segmented">
          {RANGE_PRESETS.map((r) => (
            <button key={r} className={range === r ? 'on' : ''} onClick={() => set('range', r)}>
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-range">
        {from} → {to}
      </div>
    </div>
  );
}
