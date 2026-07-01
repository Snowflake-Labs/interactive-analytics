-- TPC-H benchmark teardown (per scale factor)
USE ROLE ACCOUNTADMIN;

-- Per-scale interactive warehouses
DROP WAREHOUSE IF EXISTS IW_TPCH_BENCH_WH_{{SCALE}};

-- Per-scale standard warehouses
DROP WAREHOUSE IF EXISTS TPCH_BENCH_WH_{{SCALE}};
