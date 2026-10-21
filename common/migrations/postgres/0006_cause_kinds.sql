-- Amendment A23: hypotheses name a cause kind from a closed list (common/kinds.py). NOT VALID keeps
-- the rows written before the list existed (symptoms were 'latency'); every new row is checked.
ALTER TABLE hypotheses ADD CONSTRAINT hypotheses_cause_kind_closed
  CHECK (cause_kind IN ('bad_deploy', 'slow_query', 'pool_exhaustion', 'dependency_outage', 'memory_leak', 'noisy_neighbor', 'config_change', 'cache_stampede', 'connection_refused', 'cpu_throttling', 'other')) NOT VALID;
