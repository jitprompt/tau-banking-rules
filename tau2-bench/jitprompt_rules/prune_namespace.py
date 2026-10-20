"""Turn a duplicate of the XL namespace into tier L, M or S by deleting the
documents outside the tier. Dry run by default; pass --apply to delete.

Refuses to run unless every tier document is present and ready (i.e. the
namespace really is a complete XL copy), and verifies afterwards that the
namespace holds exactly the tier's documents.

    JITPROMPT_KEY_RULES_M=... uv run python jitprompt_rules/prune_namespace.py --tier M --apply
"""

import argparse
import json
import os
import sys

from ingest_jitprompt import OUT_DIR, TIERS_DIR, Client


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", required=True, choices=["S", "M", "L"])
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args()

    key = os.environ.get(f"JITPROMPT_KEY_RULES_{args.tier}")
    if not key:
        sys.exit(f"set JITPROMPT_KEY_RULES_{args.tier}")
    if key == os.environ.get("JITPROMPT_KEY_RULES_XL"):
        sys.exit("refusing: this is the XL namespace's key")
    client = Client(key)

    wanted = {f"{p.stem}.md" for p in (TIERS_DIR / args.tier).glob("*.json")}
    listing = client.request("GET", "/documents").json()
    present = {d["source_name"]: d for d in listing}
    missing = wanted - present.keys()
    not_ready = [n for n in wanted & present.keys() if present[n]["status"] != "ready"]
    if missing or not_ready:
        sys.exit(f"not a complete copy: {len(missing)} tier docs missing, {len(not_ready)} not ready")

    extra = sorted(present.keys() - wanted)
    print(f"tier {args.tier}: keep {len(wanted)}, delete {len(extra)} of {len(present)}")
    if not args.apply:
        print("dry run; pass --apply to delete")
        return
    for i, name in enumerate(extra, 1):
        client.request("DELETE", f"/documents/{present[name]['id']}")
        if i % 50 == 0 or i == len(extra):
            print(f"  deleted {i}/{len(extra)}")

    listing = client.request("GET", "/documents").json()
    names = {d["source_name"] for d in listing}
    if names != wanted:
        sys.exit(f"MISMATCH after prune: {len(names - wanted)} extra, {len(wanted - names)} missing")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ingest_{args.tier}.json"
    out.write_text(json.dumps(
        {"tier": args.tier, "built_by": "duplicate of XL + prune", "documents": listing}, indent=2
    ))
    print(f"OK: namespace holds exactly the {len(wanted)} tier-{args.tier} docs; wrote {out}")


if __name__ == "__main__":
    main()
