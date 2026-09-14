'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Filters } from '@/components/Filters';
import { Tile } from '@/components/Tile';
import {
  Bars,
  Center,
  DataTable,
  Donut,
  Kpi,
  Points,
  StackedArea,
  StackedBars,
  TimeLine,
} from '@/components/charts';
import { CohortHeatmap } from '@/components/CohortHeatmap';
import {
  Db,
  Granularity,
  RANGE_PRESETS,
  RangePreset,
  fmtCount,
  fmtCurrency,
  fmtPct,
  num,
  p,
  t,
  u,
} from '@/lib/cube';

/**
 * The 32-tile e-commerce dashboard.
 *
 * Every tile declares only its own measures and dimensions; lib/cube.ts injects
 * the global order_date range and resolves the `Pg` / `Sf` cube name prefixes
 * from the `db` picker. That is what makes the same tile definition run against
 * both engines.
 *
 * Trend granularity scales with the selected range so a 2-year view does not ask
 * for 731 daily points.
 */

function granularityFor(range: RangePreset): Granularity {
  // Each preset picks the finest grain that still yields a readable number of
  // points, and never a single point: the trend tiles draw lines with
  // dot={false}, so a one-point series renders as an empty plot.
  if (range === '1h') return 'minute';
  if (range === '6h' || range === '1d') return 'hour';
  if (range === '7d' || range === '30d') return 'day';
  if (range === '90d') return 'week';
  return 'month';
}

function Dashboard() {
  const params = useSearchParams();
  const db = (params.get('db') === 'pg' ? 'pg' : 'sf') as Db;
  const rangeParam = params.get('range');
  const range = (RANGE_PRESETS.includes((rangeParam ?? '') as RangePreset)
    ? rangeParam
    : '30d') as RangePreset;

  const g = granularityFor(range);
  const common = { db, range };

  return (
    <main>
      <header className="page-head">
        <div>
          <h1>Postgres vs Snowflake</h1>
          <p className="subtitle">
            One Cube model, two data sources, 32 tiles over the same fact table. Each badge is the
            wall-clock round trip for that tile.
          </p>
        </div>
        <Filters db={db} range={range} />
      </header>

      {/* ---- KPIs (1-6): order_date is the only predicate ---- */}
      <div className="grid kpi-grid">
        <Tile {...common} n={1} title="Revenue" height={96} spec={{ measures: [t(db, 'revenue')] }}>
          {(rows) => (
            <Center>
              <Kpi value={fmtCurrency(num(rows[0], t(db, 'revenue')))} sub="line_total" />
            </Center>
          )}
        </Tile>

        <Tile {...common} n={2} title="Orders" height={96} spec={{ measures: [t(db, 'orderCount')] }}>
          {(rows) => (
            <Center>
              <Kpi value={fmtCount(num(rows[0], t(db, 'orderCount')))} sub="distinct order_id" />
            </Center>
          )}
        </Tile>

        <Tile {...common} n={3} title="AOV" height={96} spec={{ measures: [t(db, 'aov')] }}>
          {(rows) => (
            <Center>
              <Kpi value={fmtCurrency(num(rows[0], t(db, 'aov')))} sub="revenue / orders" />
            </Center>
          )}
        </Tile>

        <Tile {...common} n={4} title="Margin %" height={96} spec={{ measures: [t(db, 'marginPct')] }}>
          {(rows) => (
            <Center>
              <Kpi value={fmtPct(num(rows[0], t(db, 'marginPct')))} sub="margin / revenue" />
            </Center>
          )}
        </Tile>

        <Tile {...common} n={5} title="Units" height={96} spec={{ measures: [t(db, 'units')] }}>
          {(rows) => (
            <Center>
              <Kpi value={fmtCount(num(rows[0], t(db, 'units')))} sub="sum quantity" />
            </Center>
          )}
        </Tile>

        <Tile
          {...common}
          n={6}
          title="Active customers"
          height={96}
          spec={{ measures: [t(db, 'customerCount')] }}
        >
          {(rows) => (
            <Center>
              <Kpi
                value={fmtCount(num(rows[0], t(db, 'customerCount')))}
                sub="distinct user_id"
              />
            </Center>
          )}
        </Tile>
      </div>

      {/* ---- Trends (7-10) ---- */}
      <div className="grid">
        <Tile
          {...common}
          n={7}
          title="Revenue trend"
          span={2}
          spec={{ measures: [t(db, 'revenue')], granularity: g }}
        >
          {(rows) => (
            <TimeLine
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              series={[{ key: t(db, 'revenue'), label: 'Revenue' }]}
              granularity={g}
              fmt={fmtCurrency}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={8}
          title="Orders vs AOV"
          span={2}
          spec={{ measures: [t(db, 'orderCount'), t(db, 'aov')], granularity: g }}
        >
          {(rows) => (
            <TimeLine
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              series={[
                { key: t(db, 'orderCount'), label: 'Orders' },
                { key: t(db, 'aov'), label: 'AOV' },
              ]}
              granularity={g}
              fmt={fmtCount}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={9}
          title="Margin % trend"
          span={2}
          spec={{ measures: [t(db, 'marginPct')], granularity: g }}
        >
          {(rows) => (
            <TimeLine
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              series={[{ key: t(db, 'marginPct'), label: 'Margin %' }]}
              granularity={g}
              fmt={fmtPct}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={10}
          title="Revenue by sales channel over time"
          span={2}
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [t(db, 'salesChannel')],
            granularity: g,
          }}
        >
          {(rows) => (
            <StackedArea
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              seriesKey={t(db, 'salesChannel')}
              valueKey={t(db, 'revenue')}
              granularity={g}
              fmt={fmtCurrency}
            />
          )}
        </Tile>

        {/* ---- Mix and status (11-14) ---- */}
        <Tile
          {...common}
          n={11}
          title="Channel mix"
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [t(db, 'salesChannel')],
            order: { [t(db, 'revenue')]: 'desc' },
          }}
        >
          {(rows) => (
            <Donut
              rows={rows}
              labelKey={t(db, 'salesChannel')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={12}
          title="Payment method mix"
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [t(db, 'paymentMethod')],
            order: { [t(db, 'revenue')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={t(db, 'paymentMethod')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={13}
          title="Order status funnel"
          spec={{
            measures: [t(db, 'orderCount')],
            dimensions: [t(db, 'orderStatus')],
            order: { [t(db, 'orderCount')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={t(db, 'orderStatus')}
              valueKey={t(db, 'orderCount')}
              fmt={fmtCount}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={14}
          title="Fulfillment status by channel"
          span={2}
          spec={{
            measures: [t(db, 'lineCount')],
            dimensions: [t(db, 'salesChannel'), t(db, 'fulfillmentStatus')],
          }}
        >
          {(rows) => (
            <StackedBars
              rows={rows}
              xKey={t(db, 'salesChannel')}
              seriesKey={t(db, 'fulfillmentStatus')}
              valueKey={t(db, 'lineCount')}
              fmt={fmtCount}
            />
          )}
        </Tile>

        {/* ---- Product (15-19): these join DIM_PRODUCT ---- */}
        <Tile
          {...common}
          n={15}
          title="Top 10 categories by revenue"
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [p(db, 'category')],
            order: { [t(db, 'revenue')]: 'desc' },
            limit: 10,
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={p(db, 'category')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={16}
          title="Top 10 brands by margin"
          spec={{
            measures: [t(db, 'margin')],
            dimensions: [p(db, 'brand')],
            order: { [t(db, 'margin')]: 'desc' },
            limit: 10,
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={p(db, 'brand')}
              valueKey={t(db, 'margin')}
              fmt={fmtCurrency}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={17}
          title="Category revenue vs margin %"
          spec={{
            measures: [t(db, 'revenue'), t(db, 'marginPct')],
            dimensions: [p(db, 'category')],
          }}
        >
          {(rows) => (
            <Points
              rows={rows}
              labelKey={p(db, 'category')}
              xKey={t(db, 'revenue')}
              yKey={t(db, 'marginPct')}
              xFmt={fmtCurrency}
              yFmt={fmtPct}
              xLabel="Revenue"
              yLabel="Margin %"
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={18}
          title="Department revenue"
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [p(db, 'department')],
            order: { [t(db, 'revenue')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={p(db, 'department')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={19}
          title="Top 15 products by revenue"
          span={2}
          height={300}
          spec={{
            measures: [t(db, 'revenue'), t(db, 'units'), t(db, 'marginPct')],
            dimensions: [p(db, 'productName'), p(db, 'category')],
            order: { [t(db, 'revenue')]: 'desc' },
            limit: 15,
          }}
        >
          {(rows) => (
            <DataTable
              rows={rows}
              columns={[
                { key: p(db, 'productName'), label: 'Product' },
                { key: p(db, 'category'), label: 'Category' },
                { key: t(db, 'revenue'), label: 'Revenue', fmt: fmtCurrency },
                { key: t(db, 'units'), label: 'Units', fmt: fmtCount },
                { key: t(db, 'marginPct'), label: 'Margin %', fmt: fmtPct },
              ]}
            />
          )}
        </Tile>

        {/* ---- Fulfillment (20-22) ---- */}
        <Tile
          {...common}
          n={20}
          title="Avg ship lag by carrier"
          spec={{
            measures: [t(db, 'avgShipLagDays')],
            dimensions: [t(db, 'shippingCarrier')],
            filters: [{ member: t(db, 'shipDate'), operator: 'set' }],
            order: { [t(db, 'avgShipLagDays')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={t(db, 'shippingCarrier')}
              valueKey={t(db, 'avgShipLagDays')}
              fmt={(v) => `${v.toFixed(2)}d`}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={21}
          title="Avg delivery lag by method"
          spec={{
            measures: [t(db, 'avgDeliveryLagDays')],
            dimensions: [t(db, 'shippingMethod')],
            filters: [{ member: t(db, 'deliveryDate'), operator: 'set' }],
            order: { [t(db, 'avgDeliveryLagDays')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={t(db, 'shippingMethod')}
              valueKey={t(db, 'avgDeliveryLagDays')}
              fmt={(v) => `${v.toFixed(2)}d`}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={22}
          title="Delivery SLA trend (≤7d)"
          span={2}
          spec={{
            measures: [t(db, 'onTimeRate')],
            granularity: g,
            filters: [{ member: t(db, 'deliveryDate'), operator: 'set' }],
          }}
        >
          {(rows) => (
            <TimeLine
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              series={[{ key: t(db, 'onTimeRate'), label: 'On-time %' }]}
              granularity={g}
              fmt={fmtPct}
            />
          )}
        </Tile>

        {/* ---- Returns and refunds (23-25) ---- */}
        <Tile
          {...common}
          n={23}
          title="Return rate by category"
          spec={{
            measures: [t(db, 'returnRate')],
            dimensions: [p(db, 'category')],
            order: { [t(db, 'returnRate')]: 'desc' },
            limit: 10,
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={p(db, 'category')}
              valueKey={t(db, 'returnRate')}
              fmt={fmtPct}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={24}
          title="Return reasons"
          spec={{
            measures: [t(db, 'lineCount')],
            dimensions: [t(db, 'returnReason')],
            filters: [
              { member: t(db, 'isReturn'), operator: 'equals', values: ['true'] },
              { member: t(db, 'returnReason'), operator: 'set' },
            ],
            order: { [t(db, 'lineCount')]: 'desc' },
          }}
        >
          {(rows) => (
            <Donut
              rows={rows}
              labelKey={t(db, 'returnReason')}
              valueKey={t(db, 'lineCount')}
              fmt={fmtCount}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={25}
          title="Refund amount trend"
          span={2}
          spec={{
            measures: [t(db, 'refundAmount')],
            granularity: g,
            filters: [{ member: t(db, 'isRefunded'), operator: 'equals', values: ['true'] }],
          }}
        >
          {(rows) => (
            <TimeLine
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              series={[{ key: t(db, 'refundAmount'), label: 'Refunds' }]}
              granularity={g}
              fmt={fmtCurrency}
            />
          )}
        </Tile>

        {/* ---- Discounts and promos (26-27) ---- */}
        <Tile
          {...common}
          n={26}
          title="Discount rate vs revenue"
          spec={{
            measures: [t(db, 'revenue'), t(db, 'discountRate')],
            dimensions: [p(db, 'category')],
          }}
        >
          {(rows) => (
            <Points
              rows={rows}
              labelKey={p(db, 'category')}
              xKey={t(db, 'revenue')}
              yKey={t(db, 'discountRate')}
              xFmt={fmtCurrency}
              yFmt={fmtPct}
              xLabel="Revenue"
              yLabel="Discount %"
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={27}
          title="Top promo codes"
          span={2}
          height={300}
          spec={{
            measures: [t(db, 'revenue'), t(db, 'orderCount'), t(db, 'couponAmount')],
            dimensions: [t(db, 'promoCode')],
            filters: [{ member: t(db, 'promoCode'), operator: 'set' }],
            order: { [t(db, 'revenue')]: 'desc' },
            limit: 15,
          }}
        >
          {(rows) => (
            <DataTable
              rows={rows}
              columns={[
                { key: t(db, 'promoCode'), label: 'Promo code' },
                { key: t(db, 'revenue'), label: 'Revenue', fmt: fmtCurrency },
                { key: t(db, 'orderCount'), label: 'Orders', fmt: fmtCount },
                { key: t(db, 'couponAmount'), label: 'Coupon $', fmt: fmtCurrency },
              ]}
            />
          )}
        </Tile>

        {/* ---- Customer (28-32): these join DIM_USER ---- */}
        <Tile
          {...common}
          n={28}
          title="Revenue by loyalty tier"
          span={2}
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [u(db, 'loyaltyTier')],
            granularity: g,
          }}
        >
          {(rows) => (
            <StackedBars
              rows={rows}
              xKey={`${t(db, 'orderDate')}.${g}`}
              seriesKey={u(db, 'loyaltyTier')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
              granularity={g}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={29}
          title="Signup-month cohort revenue"
          span={2}
          height={330}
          spec={{
            measures: [t(db, 'revenue')],
            granularity: 'month',
            extraTimeDimensions: [{ dimension: u(db, 'signupDate'), granularity: 'month' }],
          }}
        >
          {(rows) => (
            <CohortHeatmap
              rows={rows}
              cohortKey={`${u(db, 'signupDate')}.month`}
              orderMonthKey={`${t(db, 'orderDate')}.month`}
              valueKey={t(db, 'revenue')}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={30}
          title="Revenue by acquisition channel"
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [u(db, 'acquisitionChannel')],
            order: { [t(db, 'revenue')]: 'desc' },
          }}
        >
          {(rows) => (
            <Bars
              rows={rows}
              labelKey={u(db, 'acquisitionChannel')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
              horizontal
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={31}
          title="UTM attribution"
          span={2}
          height={300}
          spec={{
            measures: [t(db, 'revenue'), t(db, 'orderCount')],
            dimensions: [t(db, 'utmSource'), t(db, 'utmCampaign')],
            order: { [t(db, 'revenue')]: 'desc' },
            limit: 15,
          }}
        >
          {(rows) => (
            <DataTable
              rows={rows}
              columns={[
                { key: t(db, 'utmSource'), label: 'Source' },
                { key: t(db, 'utmCampaign'), label: 'Campaign' },
                { key: t(db, 'revenue'), label: 'Revenue', fmt: fmtCurrency },
                { key: t(db, 'orderCount'), label: 'Orders', fmt: fmtCount },
              ]}
            />
          )}
        </Tile>

        <Tile
          {...common}
          n={32}
          title="Revenue by country and device"
          span={2}
          spec={{
            measures: [t(db, 'revenue')],
            dimensions: [u(db, 'country'), t(db, 'deviceType')],
            order: { [t(db, 'revenue')]: 'desc' },
          }}
        >
          {(rows) => (
            <StackedBars
              rows={rows}
              xKey={u(db, 'country')}
              seriesKey={t(db, 'deviceType')}
              valueKey={t(db, 'revenue')}
              fmt={fmtCurrency}
            />
          )}
        </Tile>
      </div>
    </main>
  );
}

export default function Page() {
  // useSearchParams requires a Suspense boundary in the App Router.
  return (
    <Suspense fallback={<div className="boot">Loading dashboard…</div>}>
      <Dashboard />
    </Suspense>
  );
}
