"""Freeze what each tier's jitprompt namespace looks like before the runs.

Per tier writes results/jitprompt/snapshot_<tier>.json with: server info, the
tool list (names, schemas, descriptions — used verbatim by the agent toolkit),
the default get_toc output and its Haiku token count, and every section
(8-char id prefix and full id → tau2 doc id, title, summary, token count).

    uv run --no-sync python jitprompt_rules/jitprompt_snapshot.py --tiers S M L XL
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingest_jitprompt import OUT_DIR, Client  # noqa: E402
from jitprompt_client import for_tier  # noqa: E402

COUNT_MODEL = "claude-haiku-5-5"


def count_tokens(text: str) -> int:
    import anthropic

    return anthropic.Anthropic().messages.count_tokens(
        model=COUNT_MODEL, messages=[{"role": "user", "content": text}]
    ).input_tokens


def snapshot(tier: str) -> dict:
    mcp = for_tier(tier)
    rest = Client(os.environ[f"JITPROMPT_KEY_RULES_{tier}"])
    toc = mcp.call_tool("get_toc", {})
    docs = rest.request("GET", "/documents").json()
    sections = {}
    for d in docs:
        doc_id = d["source_name"].removesuffix(".md")
        for s in rest.request("GET", f"/documents/{d['id']}/sections").json():
            sections[s["id"]] = {
                "doc_id": doc_id, "jp_document_id": d["id"], "position": s["position"],
                "title": s["title"], "summary": s["summary"], "token_count": s["token_count"],
            }
    prefixes = {}
    for sid in sections:
        prefixes.setdefault(sid[:8], []).append(sid)
    return {
        "tier": tier,
        "server": mcp.server_info,
        "tools": mcp.list_tools(),
        "n_documents": len(docs),
        "statuses": sorted({d["status"] for d in docs}),
        "n_sections": len(sections),
        "sections_per_doc": round(len(sections) / max(len(docs), 1), 2),
        "ambiguous_prefixes": {p: ids for p, ids in prefixes.items() if len(ids) > 1},
        "toc_chars": len(toc),
        "toc_tokens": count_tokens(toc),
        "toc": toc,
        "documents": {d["source_name"].removesuffix(".md"): {"jp_id": d["id"], "title": d["title"],
                      "summary": d["summary"], "section_count": d["section_count"]} for d in docs},
        "sections": sections,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiers", nargs="+", default=["S", "M", "L", "XL"])
    args = parser.parse_args()
    for tier in args.tiers:
        snap = snapshot(tier)
        (OUT_DIR / f"snapshot_{tier}.json").write_text(json.dumps(snap, indent=2))
        print(f"{tier}: {snap['n_documents']} docs {snap['statuses']}, {snap['n_sections']} sections "
              f"({snap['sections_per_doc']}/doc), get_toc {snap['toc_tokens']} tokens, "
              f"{len(snap['ambiguous_prefixes'])} ambiguous id prefixes, server {snap['server']['serverInfo']}")


if __name__ == "__main__":
    main()
