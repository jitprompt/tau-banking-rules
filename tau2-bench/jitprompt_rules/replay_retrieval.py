"""Offline retrieval replay: do the retrievers surface each task's required docs?

No agent in the loop. For every (tier, task, query) it records which tau2 docs
come back from
  - jitprompt search_instructions(plan)  (≤4 sections → their documents)
  - jitprompt get_toc(query=plan)        (≤15 documents)
  - tau2 BM25 KB_search, top 10 (repo default) and top 4 (equal-size cut)
and how many tokens each answer costs (chars/4; relative comparison only).

Queries:
  --source plans   one agent-style plan per task, written once by Haiku from the
                   user-simulator scenario (cached in results/replay/plans.json)
  --source logged  every query the agents actually issued (retrieval_calls.jsonl)

Writes results/replay/replay_<source>.csv and prints a recall summary.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from build_tiers import TASK_IDS, TASKS  # noqa: E402
from jitprompt_client import for_tier  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/replay"
SNAPSHOTS = ROOT / "results/jitprompt"
TIERS = ["S", "XL"]
RULE_DOC_IDS = {p.stem for p in (Path(__file__).parent / "rule_docs").glob("*.json")}


def load_tasks() -> dict[str, dict]:
    return {t["id"]: t for t in TASKS}
PLAN_MODEL = "claude-haiku-5-5"
PLAN_PROMPT = """You are a customer-service agent at a bank. Below is the script of the customer who is about to contact you (you will not see this script in real life, only what the customer says). Write ONE sentence describing what you, the agent, are about to do and what policy guidance you need, as you would phrase a search of the bank's internal knowledge base. Do not include the customer's personal details.

<customer_script>
{script}
</customer_script>"""

DOC_REF = re.compile(r"\[doc ([0-9a-f]{8})\]")


ALSO_MATCHED = "Also matched, not shown"


def returned_part(text: str) -> str:
    """jitprompt ≥1.3 ends a search with documents that matched but were NOT returned
    ("Also matched, not shown …", same [doc …] tags); only the part before counts as retrieved."""
    i = text.find(ALSO_MATCHED)
    return text if i < 0 else text[:i]


def make_plans() -> dict[str, str]:
    path = OUT / "plans.json"
    if path.exists():
        return json.loads(path.read_text())
    import anthropic

    from cost import Ledger

    client, ledger, plans = anthropic.Anthropic(), Ledger(), {}
    for task_id, task in load_tasks().items():
        msg = client.messages.create(
            model=PLAN_MODEL, max_tokens=200, thinking={"type": "disabled"},
            messages=[{"role": "user", "content": PLAN_PROMPT.format(script=task["user_scenario"]["instructions"])}],
        )
        u = msg.usage
        ledger.record({"prompt_tokens": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
                       "cache_read_input_tokens": u.cache_read_input_tokens, "cache_creation_input_tokens": u.cache_creation_input_tokens,
                       "completion_tokens": u.output_tokens}, role="replay_plan", batch="replay")
        plans[task_id] = msg.content[0].text.strip()
        print(f"{task_id}: {plans[task_id]}")
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plans, indent=2))
    return plans


def logged_queries() -> list[tuple[str, str, str]]:
    """(tier, task_id, query) for every query issued in the agent runs."""
    rows = []
    path = ROOT / "results/retrieval_calls.jsonl"
    for line in path.read_text().splitlines():
        r = json.loads(line)
        q = r["args"].get("plan") or r["args"].get("query")
        if q and r.get("batch") == "pilot" and r["tool"] in ("search_instructions", "KB_search", "get_toc"):
            rows.append((r["tier"], r["task_id"], q))
    return sorted(set(rows))


def bm25_pipeline(tier: str):
    from tau2.domains.banking_knowledge import retrieval
    from tau2.domains.banking_knowledge.data_model import KnowledgeBase

    kb = KnowledgeBase.load(str(ROOT / "data/tiers" / tier))
    docs = [{"id": d.id, "text": d.content, "title": d.title} for d in sorted(kb.documents.values(), key=lambda d: d.id)]
    original = retrieval.get_or_create_docs
    retrieval.get_or_create_docs = lambda _kb: docs  # upstream caches docs globally, not per KB
    try:
        return retrieval.create_bm25_retrieval_pipeline(kb, top_k=10)
    finally:
        retrieval.get_or_create_docs = original


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["plans", "logged"], default="plans")
    parser.add_argument("--tiers", nargs="+", default=TIERS)
    args = parser.parse_args()

    tasks = load_tasks()
    if args.source == "plans":
        plans = make_plans()
        queries = [(t, tid, plans[tid]) for t in args.tiers for tid in TASK_IDS]
    else:
        queries = [q for q in logged_queries() if q[0] in args.tiers]

    rows = []
    for tier in args.tiers:
        snap = json.loads((SNAPSHOTS / f"snapshot_{tier}.json").read_text())
        jp_doc = {v["jp_id"][:8]: k for k, v in snap["documents"].items()}
        bm25 = bm25_pipeline(tier)
        mcp = for_tier(tier)
        for _, task_id, query in [q for q in queries if q[0] == tier]:
            required = set(tasks[task_id]["required_documents"])
            rule_docs = required & RULE_DOC_IDS
            search = mcp.call_tool("search_instructions", {"plan": query})
            toc = mcp.call_tool("get_toc", {"query": query})
            bm = [doc_id for doc_id, _ in bm25.retrieve(query, top_k=10)]
            bm_text = sum(len(c) for c in (bm25.get_document_content(d) or "" for d in bm))
            results = {
                "jp_search": ([jp_doc.get(p) for p in DOC_REF.findall(returned_part(search))], len(search)),
                "jp_toc_query": ([jp_doc.get(p) for p in DOC_REF.findall(toc)], len(toc)),
                "bm25_top10": (bm, bm_text),
                "bm25_top4": (bm[:4], sum(len(bm25.get_document_content(d) or "") for d in bm[:4])),
            }
            for method, (docs, chars) in results.items():
                ranked = list(dict.fromkeys(d for d in docs if d))
                hits = [d for d in ranked if d in required]
                rows.append({
                    "source": args.source, "tier": tier, "task_id": task_id, "method": method, "query": query,
                    "n_required": len(required), "n_returned_docs": len(ranked), "n_hit": len(hits),
                    "recall": round(len(hits) / len(required), 3), "any_hit": int(bool(hits)),
                    "first_hit_rank": next((i + 1 for i, d in enumerate(ranked) if d in required), ""),
                    "triggered": int(task_id.endswith("_t")),
                    "n_rule_docs": len(rule_docs), "rule_hit": int(bool(rule_docs & set(ranked))),
                    "rule_recall": round(len(rule_docs & set(ranked)) / len(rule_docs), 3),
                    "tokens_approx": chars // 4,
                })
        print(f"tier {tier} done")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"replay_{args.source}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'tier':<4} {'method':<13} {'recall':>7} {'any_hit':>8} {'rule_hit(trig)':>15} {'rule_hit(all)':>14} {'tokens':>7}")
    for tier in args.tiers:
        for method in ("jp_search", "jp_toc_query", "bm25_top4", "bm25_top10"):
            rs = [r for r in rows if r["tier"] == tier and r["method"] == method]
            if rs:
                trig = [r for r in rs if r["triggered"]]
                print(f"{tier:<4} {method:<13} {sum(r['recall'] for r in rs) / len(rs):>7.2f} "
                      f"{sum(r['any_hit'] for r in rs) / len(rs):>8.2f} "
                      f"{sum(r['rule_hit'] for r in trig) / max(len(trig), 1):>15.2f} "
                      f"{sum(r['rule_hit'] for r in rs) / len(rs):>14.2f} {sum(r['tokens_approx'] for r in rs) // len(rs):>7}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
