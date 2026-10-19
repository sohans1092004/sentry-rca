"""The closed list of cause kinds a hypothesis may name (Amendment A23). `other` is for a cause outside
the list and for downstream symptoms, which have no cause kind of their own. `no_fault` is a scenario,
not a cause, so it is not a kind: its expected outcome is INSUFFICIENT_EVIDENCE."""

ORIGINAL = ["bad_deploy", "slow_query", "pool_exhaustion", "dependency_outage", "memory_leak", "noisy_neighbor"]
ADDED = ["config_change", "cache_stampede", "connection_refused", "cpu_throttling"]  # test-set scenarios
CAUSE_KINDS = [*ORIGINAL, *ADDED, "other"]
