'use client';

import { useEffect, useRef } from 'react';
import type { TopLevelSpec } from 'vega-lite';
import { Row, num } from '@/lib/cube';

/**
 * Signup-month cohort revenue (tile 29). This is the one tile Recharts has no
 * good primitive for — a two-dimensional heatmap of signup cohort against order
 * month — so it uses a Vega-Lite spec directly.
 *
 * Embedded via vega-embed rather than react-vega: react-vega's peer range stops
 * at React 18 and this app is on 19.
 */
export function CohortHeatmap({
  rows,
  cohortKey,
  orderMonthKey,
  valueKey,
}: {
  rows: Row[];
  cohortKey: string;
  orderMonthKey: string;
  valueKey: string;
}) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    const values = rows.map((r) => ({
      cohort: String(r[cohortKey] ?? '').slice(0, 7),
      month: String(r[orderMonthKey] ?? '').slice(0, 7),
      revenue: num(r, valueKey),
    }));

    const spec: TopLevelSpec = {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      data: { values },
      mark: 'rect',
      width: 'container',
      height: 270,
      encoding: {
        x: {
          field: 'month',
          type: 'ordinal',
          title: 'Order month',
          axis: { labelAngle: -45, labelFontSize: 9 },
        },
        y: {
          field: 'cohort',
          type: 'ordinal',
          title: 'Signup cohort',
          axis: { labelFontSize: 9 },
        },
        color: {
          field: 'revenue',
          type: 'quantitative',
          title: 'Revenue',
          scale: { scheme: 'blues' },
        },
        tooltip: [
          { field: 'cohort', title: 'Cohort' },
          { field: 'month', title: 'Month' },
          { field: 'revenue', type: 'quantitative', format: ',.0f', title: 'Revenue' },
        ],
      },
      config: {
        view: { stroke: 'transparent' },
        axis: { labelColor: '#8a94a6', titleColor: '#8a94a6', titleFontSize: 10 },
        legend: { labelColor: '#8a94a6', titleColor: '#8a94a6', labelFontSize: 9, titleFontSize: 10 },
      },
    };

    let disposed = false;
    let view: { finalize: () => void } | null = null;

    // Dynamic import keeps vega out of the initial bundle; it is only needed by
    // this one tile.
    import('vega-embed').then(({ default: embed }) => {
      if (disposed || !host.current) return;
      embed(host.current, spec, { actions: false, renderer: 'canvas' })
        .then((r) => {
          if (disposed) {
            r.view.finalize();
            return;
          }
          view = r.view;
        })
        .catch(() => {
          /* the Tile error boundary already covers query failures; a render
             failure here should not take down the page */
        });
    });

    return () => {
      disposed = true;
      view?.finalize();
      el.replaceChildren();
    };
  }, [rows, cohortKey, orderMonthKey, valueKey]);

  return <div ref={host} style={{ width: '100%' }} />;
}
