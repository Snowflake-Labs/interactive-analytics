WITH boundaries AS (
  SELECT
    MAX(L_SHIPDATE) AS end_date,
    DATEADD(year, -3, MAX(L_SHIPDATE)) AS start_date
  FROM LINEITEM_DASHBOARD
)
SELECT l.L_ORDERKEY AS order_id,
             MAX(l.L_SHIPDATE) AS order_date,
             l.L_ORDERSTATUS AS status,
             l.L_MKTSEGMENT AS market_segment,
             l.L_REGIONNAME AS region,
             ROUND(SUM(l.L_EXTENDEDPRICE * (1 - l.L_DISCOUNT)), 2) AS total_amount
FROM LINEITEM_DASHBOARD l
CROSS JOIN boundaries
WHERE l.L_SHIPDATE BETWEEN boundaries.start_date AND boundaries.end_date
GROUP BY l.L_ORDERKEY, l.L_ORDERSTATUS, l.L_MKTSEGMENT, l.L_REGIONNAME
ORDER BY MAX(l.L_SHIPDATE) DESC, l.L_ORDERKEY DESC
LIMIT 20