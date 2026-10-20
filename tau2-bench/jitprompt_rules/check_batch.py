"""Check a finished (arm, tier) cell for runs that ended on infrastructure trouble
(network drop, laptop sleep, API errors) rather than a normal conversation end.

    uv run --no-sync python jitprompt_rules/check_batch.py jb_pilot3_jitprompt_S          # report
    uv run --no-sync python jitprompt_rules/check_batch.py jb_pilot3_jitprompt_S --purge  # drop them

With --purge the bad runs are removed from that cell's results.json (a backup is
kept next to it), so re-running the same run.py command (--auto-resume) redoes
exactly those tasks. Missing tasks are listed too; a re-run fills them.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_tiers import TASK_IDS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
NORMAL = {"user_stop", "agent_stop", "max_steps"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cell", help="save name, e.g. jb_pilot3_jitprompt_S")
    p.add_argument("--purge", action="store_true")
    args = p.parse_args()

    path = REPO / "data/simulations" / args.cell / "results.json"
    if not path.exists():
        sys.exit(f"no results at {path}")
    data = json.loads(path.read_text())
    sims = data["simulations"]
    bad = [s for s in sims if s["termination_reason"] not in NORMAL]
    missing = sorted(set(TASK_IDS) - {s["task_id"] for s in sims})
    print(f"{args.cell}: {len(sims)} runs, {len(bad)} abnormal, {len(missing)} missing")
    for s in bad:
        print(f"  {s['task_id']} trial {s.get('trial')}: {s['termination_reason']}")
    if missing:
        print(f"  missing: {' '.join(missing)}")
    if args.purge and bad:
        backup = path.with_name(f"results.backup-{int(time.time())}.json")
        shutil.copy2(path, backup)
        data["simulations"] = [s for s in sims if s["termination_reason"] in NORMAL]
        path.write_text(json.dumps(data))
        print(f"removed {len(bad)} abnormal runs (backup {backup.name}); re-run the same run.py command to redo them")
    sys.exit(1 if bad or missing else 0)


if __name__ == "__main__":
    main()
