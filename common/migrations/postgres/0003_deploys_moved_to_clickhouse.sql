-- Deploys moved to ClickHouse (Amendment A9). `python -m common.migrate` copies any existing rows
-- into ClickHouse before this file runs.
DROP TABLE IF EXISTS deploys;
