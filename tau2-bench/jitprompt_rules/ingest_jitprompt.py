"""Upload one corpus tier into its production jitprompt namespace, as-is.

Each tau2 document becomes `<doc_id>.md` whose bytes are exactly the JSON
`content` field, uploaded with `title` = the JSON `title`. No front matter, no
restructuring. The doc id travels only as the file name (jitprompt's
`source_name`), which is how sections are mapped back to tau2 docs.

Idempotent: documents already present (matched by source_name) are skipped, and
jitprompt dedups identical content anyway. After uploading it polls until every
document is `ready` or `failed` and writes results/jitprompt/ingest_<tier>.json.

    JITPROMPT_KEY_RULES_S=... uv run python jitprompt_rules/ingest_jitprompt.py --tier S
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # tau2-bench/.env, same file tau2 reads
TIERS_DIR = ROOT / "data/tiers"
OUT_DIR = ROOT / "results/jitprompt"
BASE_URL = os.environ.get("JITPROMPT_URL", "https://app.jitprompt.com")
# Stay well under the key's rate limit.
MIN_INTERVAL = 0.25


class Client:
    def __init__(self, key: str):
        self.http = httpx.Client(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=60
        )
        self._last = 0.0

    def request(self, method: str, path: str, ok: tuple[int, ...] = (), **kwargs) -> httpx.Response:
        """`ok`: extra status codes returned instead of treated as errors (e.g. 404 on a DELETE
        retried after a dropped connection already removed the document)."""
        for attempt in range(6):
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.http.request(method, path, **kwargs)
            except httpx.TransportError as e:
                print(f"  transport error ({e}); retrying", file=sys.stderr)
                time.sleep(2**attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(float(resp.headers.get("retry-after", 2**attempt)))
                continue
            if resp.status_code in ok:
                return resp
            if resp.is_error:
                sys.exit(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
            return resp
        resp.raise_for_status()
        return resp


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", required=True, choices=["S", "M", "L", "XL"])
    parser.add_argument("--no-wait", action="store_true", help="upload only, don't poll")
    args = parser.parse_args()

    key = os.environ.get(f"JITPROMPT_KEY_RULES_{args.tier}")
    if not key:
        sys.exit(f"set JITPROMPT_KEY_RULES_{args.tier}")
    client = Client(key)

    docs = [json.loads(p.read_text()) for p in sorted((TIERS_DIR / args.tier).glob("*.json"))]
    existing = {d["source_name"]: d for d in client.request("GET", "/documents").json()}
    print(f"tier {args.tier}: {len(docs)} docs, {len(existing)} already in namespace")
    unexpected = set(existing) - {f"{d['id']}.md" for d in docs}
    if unexpected:
        sys.exit(f"namespace holds documents outside this tier: {sorted(unexpected)[:5]}…")

    for i, doc in enumerate(docs, 1):
        name = f"{doc['id']}.md"
        if name in existing:
            continue
        resp = client.request(
            "POST", "/documents",
            files={"file": (name, doc["content"].encode("utf-8"), "text/markdown")},
            data={"title": doc["title"]},
        ).json()
        print(f"  [{i}/{len(docs)}] {name} -> {resp['document_id'][:8]} {resp['status']}"
              + (" (deduped)" if resp.get("deduped") else ""))

    if args.no_wait:
        return
    start = time.monotonic()
    while True:
        listing = client.request("GET", "/documents").json()
        by_status: dict[str, int] = {}
        for d in listing:
            by_status[d["status"]] = by_status.get(d["status"], 0) + 1
        print(f"  {time.monotonic() - start:6.0f}s {by_status}")
        if all(d["status"] in ("ready", "failed") for d in listing) and len(listing) >= len(docs):
            break
        time.sleep(30)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ingest_{args.tier}.json"
    out.write_text(json.dumps({"base_url": BASE_URL, "tier": args.tier, "documents": listing}, indent=2))
    failed = [d for d in listing if d["status"] == "failed"]
    print(f"wrote {out}; {len(listing) - len(failed)} ready, {len(failed)} failed")
    for d in failed:
        print(f"  FAILED {d['source_name']}: {d['error']}")


if __name__ == "__main__":
    main()
