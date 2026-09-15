/**
 * One shared definition, two data sources.
 *
 * This is the TEMPLATE. `uv run gen_env.py` renders it to model/cubes.js with the
 * table names from .env; that output is gitignored, so no account, database or
 * schema name is ever committed. Edit this file, never model/cubes.js.
 *
 * Point the tables at interactive tables, standard tables, or any tables whose
 * columns match — the model only cares about column names.
 *
 * Structure is dictated by a hard constraint in Cube's schema transpiler: member
 * references (`${revenue}`) and cube references in joins are resolved
 * *statically*, from the string literal passed to `cube()`. A generated name --
 * `cube(T, {...})` where T is a variable -- makes every `${member}` fail with
 * "revenue is not defined". So the cube names here are literals, and sharing
 * happens through `extends` instead of a loop.
 *
 * The base cubes are `public: false`: they exist only to be extended and must
 * never be queried directly (their sql_table is a placeholder).
 *
 * The only per-source overrides are the five ship/delivery lag measures, because
 * timestamp difference has no portable spelling: Postgres subtracts timestamps
 * into an interval, Snowflake needs DATEDIFF.
 *
 * Identifier casing: all column references are unquoted lowercase. Postgres
 * stores them lowercase; Snowflake folds unquoted identifiers to uppercase and
 * matches. Never quote a column here or one side will break.
 */

// __TABLES__
// gen_env.py substitutes this marker with the table names from .env.
//
// It has to be substituted into the file rather than read from the environment:
// Cube's model sandbox exposes neither `process`, `require` nor `module`, and
// top-level consts are not shared between model files.

// ---------------------------------------------------------------------------
// Dialect-specific lag measures, expressed as a factory so the two concrete
// fact cubes stay identical apart from the SQL spelling.
// ---------------------------------------------------------------------------
const lagMeasures = (lagDays) => ({
  avgShipLagDays: {
    sql: () => lagDays('order_date', 'ship_date'),
    type: 'avg',
  },
  avgDeliveryLagDays: {
    sql: () => lagDays('order_date', 'delivery_date'),
    type: 'avg',
  },
  deliveredCount: {
    type: 'count',
    filters: [{ sql: () => `delivery_date IS NOT NULL` }],
  },
  // Delivered within 7 days of the order.
  onTimeCount: {
    type: 'count',
    filters: [
      {
        sql: () =>
          `delivery_date IS NOT NULL AND ${lagDays('order_date', 'delivery_date')} <= 7`,
      },
    ],
  },
  // Written as a raw aggregate rather than `${onTimeCount}/${deliveredCount}`:
  // members created inside this factory are invisible to Cube's static
  // transpiler, so a member reference to them would fail to resolve.
  onTimeRate: {
    sql: () =>
      `100.0 * COUNT(CASE WHEN delivery_date IS NOT NULL AND ${lagDays(
        'order_date',
        'delivery_date',
      )} <= 7 THEN 1 END) / NULLIF(COUNT(CASE WHEN delivery_date IS NOT NULL THEN 1 END), 0)`,
    type: 'number',
  },
});

const PG_LAG = (a, b) => `EXTRACT(EPOCH FROM (${b} - ${a})) / 86400.0`;
const SF_LAG = (a, b) => `DATEDIFF('second', ${a}, ${b}) / 86400.0`;

// ---------------------------------------------------------------------------
// Base cubes: every measure and dimension the 32 tiles need.
// ---------------------------------------------------------------------------

cube('BaseTransactions', {
  sql_table: 'placeholder',
  public: false,
  // Needed even though this cube is never queried: Cube builds a SQL dialect
  // for every distinct data_source it sees, and omitting this one leaves a
  // 'default' source with no configured type -> "Unsupported db type: undefined".
  data_source: 'sf',
  pre_aggregations: {}, // deliberately none - see cube.js

  measures: {
    revenue: { sql: 'line_total', type: 'sum', format: 'currency' },
    // Grain is the order line, so order counts must be distinct on order_id.
    orderCount: { sql: 'order_id', type: 'countDistinct' },
    lineCount: { type: 'count' },
    units: { sql: 'quantity', type: 'sum' },
    customerCount: { sql: 'user_id', type: 'countDistinct' },

    margin: { sql: 'margin_amount', type: 'sum', format: 'currency' },
    discountAmount: { sql: 'discount_amount', type: 'sum', format: 'currency' },
    taxAmount: { sql: 'tax_amount', type: 'sum', format: 'currency' },
    shippingAmount: { sql: 'shipping_amount', type: 'sum', format: 'currency' },
    couponAmount: { sql: 'coupon_amount', type: 'sum', format: 'currency' },
    refundAmount: { sql: 'refund_amount', type: 'sum', format: 'currency' },

    aov: {
      sql: () => `${revenue} / NULLIF(${orderCount}, 0)`,
      type: 'number',
      format: 'currency',
    },
    marginPct: {
      sql: () => `100.0 * ${margin} / NULLIF(${revenue}, 0)`,
      type: 'number',
    },
    discountRate: {
      sql: () => `100.0 * ${discountAmount} / NULLIF(${revenue} + ${discountAmount}, 0)`,
      type: 'number',
    },
    returnLineCount: {
      type: 'count',
      filters: [{ sql: () => `is_return` }],
    },
    returnRate: {
      sql: () => `100.0 * ${returnLineCount} / NULLIF(${lineCount}, 0)`,
      type: 'number',
    },
  },

  dimensions: {
    transactionId: { sql: 'transaction_id', type: 'number', primary_key: true },
    orderId: { sql: 'order_id', type: 'number' },
    productId: { sql: 'product_id', type: 'number' },
    userId: { sql: 'user_id', type: 'number' },

    orderDate: { sql: 'order_date', type: 'time' },
    shipDate: { sql: 'ship_date', type: 'time' },
    deliveryDate: { sql: 'delivery_date', type: 'time' },

    orderStatus: { sql: 'order_status', type: 'string' },
    fulfillmentStatus: { sql: 'fulfillment_status', type: 'string' },
    paymentStatus: { sql: 'payment_status', type: 'string' },
    paymentMethod: { sql: 'payment_method', type: 'string' },
    salesChannel: { sql: 'sales_channel', type: 'string' },
    shippingMethod: { sql: 'shipping_method', type: 'string' },
    shippingCarrier: { sql: 'shipping_carrier', type: 'string' },
    deviceType: { sql: 'device_type', type: 'string' },
    promoCode: { sql: 'promo_code', type: 'string' },
    returnReason: { sql: 'return_reason', type: 'string' },
    utmSource: { sql: 'utm_source', type: 'string' },
    utmMedium: { sql: 'utm_medium', type: 'string' },
    utmCampaign: { sql: 'utm_campaign', type: 'string' },

    isReturn: { sql: 'is_return', type: 'boolean' },
    isRefunded: { sql: 'is_refunded', type: 'boolean' },
    isGift: { sql: 'is_gift', type: 'boolean' },
  },
});

cube('BaseProducts', {
  sql_table: 'placeholder',
  public: false,
  // Needed even though this cube is never queried: Cube builds a SQL dialect
  // for every distinct data_source it sees, and omitting this one leaves a
  // 'default' source with no configured type -> "Unsupported db type: undefined".
  data_source: 'sf',
  pre_aggregations: {},
  measures: {
    productCount: { type: 'count' },
    avgRating: { sql: 'rating', type: 'avg' },
    avgListPrice: { sql: 'list_price', type: 'avg', format: 'currency' },
    stockQuantity: { sql: 'stock_quantity', type: 'sum' },
  },
  dimensions: {
    productId: { sql: 'product_id', type: 'number', primary_key: true },
    sku: { sql: 'sku', type: 'string' },
    productName: { sql: 'product_name', type: 'string' },
    category: { sql: 'category', type: 'string' },
    subcategory: { sql: 'subcategory', type: 'string' },
    department: { sql: 'department', type: 'string' },
    brand: { sql: 'brand', type: 'string' },
    supplierCountry: { sql: 'supplier_country', type: 'string' },
    season: { sql: 'season', type: 'string' },
    warehouseLocation: { sql: 'warehouse_location', type: 'string' },
    isActive: { sql: 'is_active', type: 'boolean' },
    isFeatured: { sql: 'is_featured', type: 'boolean' },
  },
});

cube('BaseUsers', {
  sql_table: 'placeholder',
  public: false,
  // Needed even though this cube is never queried: Cube builds a SQL dialect
  // for every distinct data_source it sees, and omitting this one leaves a
  // 'default' source with no configured type -> "Unsupported db type: undefined".
  data_source: 'sf',
  pre_aggregations: {},
  measures: {
    userCount: { type: 'count' },
    lifetimeValue: { sql: 'lifetime_value', type: 'sum', format: 'currency' },
    avgChurnProbability: { sql: 'churn_probability', type: 'avg' },
    avgEngagementScore: { sql: 'engagement_score', type: 'avg' },
  },
  dimensions: {
    userId: { sql: 'user_id', type: 'number', primary_key: true },
    country: { sql: 'country', type: 'string' },
    state: { sql: 'state', type: 'string' },
    city: { sql: 'city', type: 'string' },
    loyaltyTier: { sql: 'loyalty_tier', type: 'string' },
    accountStatus: { sql: 'account_status', type: 'string' },
    acquisitionChannel: { sql: 'acquisition_channel', type: 'string' },
    incomeBand: { sql: 'income_band', type: 'string' },
    deviceType: { sql: 'device_type', type: 'string' },
    signupDate: { sql: 'signup_date', type: 'time' },
  },
});

// ---------------------------------------------------------------------------
// dataSource pg: Postgres
// ---------------------------------------------------------------------------

cube('PgTransactions', {
  extends: BaseTransactions,
  sql_table: TABLES.PG_FACT,
  data_source: 'pg',
  public: true,
  measures: lagMeasures(PG_LAG),
  joins: {
    PgProducts: {
      relationship: 'many_to_one',
      sql: () => `${CUBE}.product_id = ${PgProducts}.product_id`,
    },
    PgUsers: {
      relationship: 'many_to_one',
      sql: () => `${CUBE}.user_id = ${PgUsers}.user_id`,
    },
  },
});

cube('PgProducts', {
  extends: BaseProducts,
  sql_table: TABLES.PG_PRODUCT,
  data_source: 'pg',
  public: true,
});

cube('PgUsers', {
  extends: BaseUsers,
  sql_table: TABLES.PG_USER,
  data_source: 'pg',
  public: true,
});

// ---------------------------------------------------------------------------
// dataSource sf: Snowflake
// ---------------------------------------------------------------------------

cube('SfTransactions', {
  extends: BaseTransactions,
  sql_table: TABLES.SF_FACT,
  data_source: 'sf',
  public: true,
  measures: lagMeasures(SF_LAG),
  joins: {
    SfProducts: {
      relationship: 'many_to_one',
      sql: () => `${CUBE}.product_id = ${SfProducts}.product_id`,
    },
    SfUsers: {
      relationship: 'many_to_one',
      sql: () => `${CUBE}.user_id = ${SfUsers}.user_id`,
    },
  },
});

cube('SfProducts', {
  extends: BaseProducts,
  sql_table: TABLES.SF_PRODUCT,
  data_source: 'sf',
  public: true,
});

cube('SfUsers', {
  extends: BaseUsers,
  sql_table: TABLES.SF_USER,
  data_source: 'sf',
  public: true,
});
