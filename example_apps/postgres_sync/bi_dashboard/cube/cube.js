/**
 * Cube Core configuration.
 *
 * Both data sources are wired through env vars using Cube's
 * CUBEJS_DS_{dataSource}_DB_* convention (see ../gen_env.py):
 *
 *   sf -> Snowflake (interactive or standard tables)
 *   pg -> Postgres (Snowflake Postgres, RDS/Aurora, Cloud SQL, self-hosted)
 *
 * Deliberately no `dbType` here. Defining it -- even as a function of
 * dataSource -- shadows the CUBEJS_DS_*_DB_TYPE resolution and every query
 * fails with "Unsupported db type: undefined".
 *
 * ## Result caching is off end to end
 *
 * The demo exists to show how a 134.6M-row analytical query behaves on each
 * engine, so no layer may serve a previously computed answer:
 *
 *   1. Cube's pre-aggregations -- every cube declares `pre_aggregations: {}`,
 *      and CUBEJS_SCHEDULED_REFRESH_DEFAULT=false.
 *   2. Cube's result cache -- Cube Core exposes no switch for this, so the client
 *      makes every request unique instead (see `cacheBuster` in
 *      ../web/lib/cube.ts). Measured: `renewQuery: true`, a volatile per-cube
 *      `refresh_key`, `refreshKeyRenewalThreshold: 0` and
 *      `skipExternalCacheAndQueue` were each tried and none worked -- four
 *      identical requests still produced exactly one SQL execution, with repeats
 *      answered in ~0.08s.
 *   3. Snowflake's result cache -- `USE_CACHED_RESULT = FALSE`, set per session by
 *      the driver subclass below. Without it a repeat replays a cached result in
 *      ~60ms and reports that as the engine's speed.
 *
 * Postgres has no query result cache to disable -- there is no equivalent of
 * USE_CACHED_RESULT. Its buffer pool and the OS page cache still warm up, but
 * they are not result reuse and cannot be turned off per session, so the two
 * sides are as comparable as the engines allow.
 *
 * Note that the interactive table's own serving layer is NOT disabled: that is
 * the feature under test, not result reuse.
 */

const { SnowflakeDriver } = require('@cubejs-backend/snowflake-driver');
const { PostgresDriver } = require('@cubejs-backend/postgres-driver');

/**
 * Cube's Snowflake driver exposes no hook for arbitrary session parameters, so
 * the one clean extension point is initConnection(), which the driver already
 * uses to set TIMEZONE, STATEMENT_TIMEOUT_IN_SECONDS and
 * QUOTED_IDENTIFIERS_IGNORE_CASE.
 *
 * Doing it here keeps the setting scoped to Cube's own sessions. The alternative
 * -- ALTER USER ... SET USE_CACHED_RESULT = FALSE -- would degrade every other
 * session belonging to the same human user.
 */
class NoResultCacheSnowflakeDriver extends SnowflakeDriver {
  async initConnection() {
    const connection = await super.initConnection();
    await this.execute(connection, 'ALTER SESSION SET USE_CACHED_RESULT = FALSE', [], false);
    return connection;
  }
}

module.exports = {
  scheduledRefreshTimer: false,

  /**
   * Required *because* driverFactory below returns driver instances rather than
   * DriverConfig objects: in that mode Cube can no longer infer a type per data
   * source and falls back to the default source's type for the SQL dialect. The
   * symptom is Snowflake SQL sent to Postgres -- every pg tile fails instantly
   * with `syntax error at or near "::"` (from `::timestamp_tz`).
   *
   * Note the asymmetry with the earlier failure mode: defining dbType *without*
   * driverFactory shadows env-based driver resolution and breaks every query with
   * "Unsupported db type: undefined". The two must be introduced together.
   */
  dbType: ({ dataSource }) => (dataSource === 'pg' ? 'postgres' : 'snowflake'),

  /**
   * Only `sf` needs a custom driver, but both branches must return a driver
   * *instance*: Cube fixes driverFactoryType on the first call and rejects a
   * later return of a different kind with "driverFactory function must return
   * either BaseDriver or DriverConfig". Mixing an instance for `sf` with a
   * `{ type: 'postgres' }` config for `pg` fails for exactly that reason.
   *
   * Passing `dataSource` is all each driver needs — both read host, credentials,
   * database, schema and SSL from the matching CUBEJS_DS_<NAME>_DB_* vars
   * themselves, so nothing is duplicated here.
   */
  driverFactory: ({ dataSource }) =>
    dataSource === 'sf'
      ? new NoResultCacheSnowflakeDriver({ dataSource })
      : new PostgresDriver({
          dataSource,
          // Abandoning a request client-side does NOT stop Postgres: it keeps
          // executing until it finishes. Without this, visiting the 30d range
          // leaves ~30 multi-minute queries churning, and every later page load
          // starves behind them -- a clean 6h load returns 32/32 tiles in under
          // 1.2s, but the same load right after a 30d visit times out on all 32.
          //
          // 80s sits just past the proxy's own 75s cutoff, so the server-side kill
          // only ever fires for queries the dashboard has already given up on.
          // node-postgres passes this straight through to the connection.
          statement_timeout: 80_000,
        }),
};
