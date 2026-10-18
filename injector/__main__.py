"""python -m injector plan|run --scenario S --seed N [--variant ambiguous|injection]"""

import argparse
import json
from dataclasses import asdict

from injector.scenarios import SCENARIOS, plan, run

ap = argparse.ArgumentParser(prog="injector")
ap.add_argument("action", choices=["plan", "run"])
ap.add_argument("--scenario", required=True, choices=SCENARIOS)
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--variant", choices=["ambiguous", "injection"])
args = ap.parse_args()
p = plan(args.scenario, args.seed, args.variant)
print(json.dumps(asdict(p) if args.action == "plan" else run(p), indent=2, default=str))
