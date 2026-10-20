"""Make a RULES_<tier> namespace (a duplicate of t-bank's XL) hold exactly data/tiers/<tier>.

    uv run --no-sync python jitprompt_rules/sync_namespace.py --tier XL          # dry run
    uv run --no-sync python jitprompt_rules/sync_namespace.py --tier XL --apply

- Rule docs (rule_docs/): buried copies replace the original of the same id (delete, then
  upload); standalone docs are uploaded. Upload = `<doc_id>.md` with the doc's exact `content`
  and `title`, as ingest_jitprompt.py does.
- Docs outside the tier are deleted (tier S only; for XL that set must be empty).
- results/jitprompt/sync_<tier>.json records the sha256 of every rule doc as uploaded, so a
  re-run re-uploads only rule docs whose text changed (e.g. after Gate 2 fixes).
- Rule docs left in `failed` status (structurer errors) are deleted and re-uploaded on a re-run.
- Ends by polling until all docs are ready and verifying the namespace's doc set equals the tier.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingest_jitprompt import OUT_DIR, TIERS_DIR, Client  # noqa: E402

RULE_DOCS = Path(__file__).parent / "rule_docs"


def sha(doc: dict) -> str:
    return hashlib.sha256((doc["title"] + "\0" + doc["content"]).encode()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tier", required=True, choices=["S", "XL"])
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    key = os.environ.get(f"JITPROMPT_KEY_RULES_{args.tier}")
    if not key:
        sys.exit(f"set JITPROMPT_KEY_RULES_{args.tier}")
    client = Client(key)
    state_path = OUT_DIR / f"sync_{args.tier}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    tier = {p.stem: json.loads(p.read_text()) for p in sorted((TIERS_DIR / args.tier).glob("*.json"))}
    rule_ids = {p.stem for p in RULE_DOCS.glob("*.json")}
    present = {d["source_name"].removesuffix(".md"): d for d in client.request("GET", "/documents").json()}

    failed = {i for i, d in present.items() if d["status"] == "failed"}
    bad_base = sorted(failed - rule_ids)
    if bad_base:
        sys.exit(f"non-rule docs in failed state (not ours to fix): {bad_base}")
    upload = [i for i in sorted(rule_ids & tier.keys())
              if state.get(i) != sha(tier[i]) or i not in present or i in failed]
    replace = [i for i in upload if i in present]          # existing version must go first
    extra = sorted(present.keys() - tier.keys())
    missing_base = sorted(tier.keys() - rule_ids - present.keys())
    if missing_base:
        sys.exit(f"namespace lacks {len(missing_base)} non-rule tier docs (not a t-bank XL copy?): {missing_base[:5]}")
    if args.tier == "XL" and extra:
        sys.exit(f"refusing: XL would delete non-tier docs {extra[:5]}")
    print(f"RULES_{args.tier}: {len(present)} present, tier {len(tier)}; upload {len(upload)} "
          f"(replacing {len(replace)}), delete {len(extra)} outside the tier")
    if not args.apply:
        print("dry run; pass --apply")
        return

    for i in replace + extra:
        client.request("DELETE", f"/documents/{present[i]['id']}", ok=(404,))
    print(f"  deleted {len(replace) + len(extra)}")
    for n, i in enumerate(upload, 1):
        doc = tier[i]
        r = client.request("POST", "/documents",
                           files={"file": (f"{i}.md", doc["content"].encode("utf-8"), "text/markdown")},
                           data={"title": doc["title"]}).json()
        state[i] = sha(doc)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
        print(f"  [{n}/{len(upload)}] {i} -> {r['document_id'][:8]} {r['status']}" + (" (deduped)" if r.get("deduped") else ""))

    start = time.monotonic()
    while True:
        listing = client.request("GET", "/documents").json()
        counts: dict[str, int] = {}
        for d in listing:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        print(f"  {time.monotonic() - start:5.0f}s {counts}")
        if all(d["status"] in ("ready", "failed") for d in listing):
            break
        time.sleep(20)
    names = {d["source_name"].removesuffix(".md") for d in listing}
    failed = [d["source_name"] for d in listing if d["status"] == "failed"]
    if names != set(tier) or failed:
        sys.exit(f"MISMATCH: {len(names - set(tier))} extra, {len(set(tier) - names)} missing, failed {failed}")
    (OUT_DIR / f"ingest_{args.tier}.json").write_text(json.dumps(
        {"tier": args.tier, "built_by": "duplicate of t-bank XL + sync_namespace.py", "documents": listing}, indent=2))
    print(f"OK: RULES_{args.tier} holds exactly the {len(tier)} tier docs, all ready")


if __name__ == "__main__":
    main()
