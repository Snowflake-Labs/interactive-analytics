-- TPC-H benchmark teardown (per scale factor)
USE ROLE SYSADMIN;

-- Per-scale interactive warehouses
DROP WAREHOUSE IF EXISTS {{SOLUTION_NAME}}_BENCH_WH_INT_{{SCALE}};

-- Per-scale standard warehouses
DROP WAREHOUSE IF EXISTS {{SOLUTION_NAME}}_BENCH_WH_STD_{{SCALE}};

-- Database
DROP DATABASE IF EXISTS {{SOLUTION_NAME}}_BENCH_DB;
