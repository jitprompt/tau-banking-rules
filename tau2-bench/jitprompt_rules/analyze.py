"""Planted-rules benchmark: results tables (and chart, see chart.py).

    uv run --no-sync python jitprompt_rules/analyze.py --batch pilot
    uv run --no-sync python jitprompt_rules/analyze.py --batch pilot --extra jitprompt_action=action

Reads data/simulations/jr_<batch>_<arm>_<tier>/results.json for arms full_prompt, rag_bm25,
jitprompt (tiers S, XL) and the references jr_<batch>_required_docs / jr_<batch>_no_rules.
Every trial in a results.json is used. Dropped rules (rules.yaml `dropped`) are excluded.

Writes to results/:
  runs.csv         one row per (task, tier, arm, trial): rule scores (check_rules.py), task
                   pass, rule position (full_prompt), retrieval calls, rule doc retrieved, tokens, cost
  summary.csv      per (tier, arm): adherence on triggered tasks, adherence given the decision
                   point was reached, false-trigger rate on controls, task pass, pass^2, cost;
                   95% bootstrap CIs resample rules (clusters), seed 0
  paired.csv       exact McNemar on (task, trial) pairs of triggered runs. PRIMARY (pre-registered):
                   jitprompt vs full_prompt at XL. Everything else is secondary.
  by_type.csv      adherence / false triggers per (tier, arm, rule type)
  by_position.csv  full_prompt adherence by the rule's position tercile in the prompt
  attribution.csv  retrieval arms, triggered runs that did not adhere: retrieval_miss (rule doc
                   never surfaced) vs attention_miss (surfaced, not followed); task_hard if the
                   required_docs reference also missed that task
"""

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_tiers import TASK_IDS  # noqa: E402  (active tasks: dropped rules excluded)
from check_rules import load_rules, score_simulation  # noqa: E402
from cost import call_cost, usage_fields  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
OUT = ROOT / "results"
TIERS = ["S", "XL"]
ARMS = ["full_prompt", "rag_bm25", "jitprompt"]
REFS = ["required_docs", "no_rules"]
RETRIEVAL_TOOLS = {"KB_search", "grep", "get_toc", "get_section", "search_instructions"}
CONTENT_TOOLS = {"KB_search", "grep", "get_section", "search_instructions"}  # return document text
BM25_ID = re.compile(r"^\s*ID: (doc_\S+)", re.M)
JP_DOC = re.compile(r"\[doc ([0-9a-f]{8})\]")
ALSO_MATCHED = "Also matched, not shown"
N_BOOT = 10_000


def returned_part(text: str) -> str:
    i = text.find(ALSO_MATCHED)
    return text if i < 0 else text[:i]


def load(name: str) -> list[dict]:
    p = REPO / "data/simulations" / name / "results.json"
    return json.loads(p.read_text())["simulations"] if p.exists() else []


def cells(batch: str, extra: dict[str, str]) -> list[tuple[str, str, str]]:
    """(arm, tier, save name). References report tier 'ref' (they run on the S task set).
    `extra` maps an additional arm to the batch it was run in (e.g. jitprompt_action=action)."""
    out = [(a, t, f"jr_{batch}_{a}_{t}") for t in TIERS for a in ARMS]
    out += [(a, t, f"jr_{b}_{a}_{t}") for a, b in extra.items() for t in TIERS]
    out += [(r, "ref", f"jr_{batch}_{r}") for r in REFS]
    return out


def task_rule_docs(rule: dict, task: dict) -> list[str]:
    """The rule docs this task needs, in rules.yaml order. The last one carries the deciding
    text: the exception (exception rules), the newer doc (superseded), the product's own doc."""
    req = set(task["required_documents"])
    return [d["id"] for d in rule["docs"] if d["id"] in req]


def run_row(sim, arm, tier, rules, tasks, manifest, jp_maps) -> dict:
    score = score_simulation(sim, rules)
    rule = rules[score["rule_id"]]
    rdocs = task_rule_docs(rule, tasks[sim["task_id"]])
    tok, cost = defaultdict(int), 0.0
    names = {}
    for m in sim["messages"]:
        if m.get("raw_data") and m["raw_data"].get("usage"):
            u = usage_fields(m["raw_data"]["usage"])
            cost += call_cost(u, m["raw_data"].get("model", "claude-haiku-5-5"))
            for k in ("input", "cache_read", "cache_write", "output"):
                tok[k] += u[k]
        if m["role"] == "assistant":
            for tc in m.get("tool_calls") or []:
                names[tc["id"]] = tc["name"]
    jp_map = jp_maps.get(tier, {})
    surfaced, n_retr = set(), 0
    for m in sim["messages"]:
        name = names.get(m.get("id")) if m["role"] == "tool" else None
        if name in RETRIEVAL_TOOLS:
            n_retr += 1
            if name in CONTENT_TOOLS:
                text = m.get("content") or ""
                surfaced |= set(BM25_ID.findall(text)) | {jp_map.get(p, p) for p in JP_DOC.findall(returned_part(text))}
    if arm in ("rag_bm25", "jitprompt"):
        retrieved, all_retrieved = int(bool(set(rdocs) & surfaced)), int(set(rdocs) <= surfaced)
    else:  # full_prompt / required_docs: the rule docs are in the prompt; no_rules: they are not
        retrieved = all_retrieved = int(arm != "no_rules")
    position = tercile = ""
    if arm == "full_prompt" and rdocs:
        position = manifest["tiers"][tier]["full_prompt"]["rule_docs"][rdocs[-1]].get("token_frac", "")
        if position != "":
            tercile = 1 if position < 1 / 3 else (2 if position < 2 / 3 else 3)
    return {
        "task_id": sim["task_id"], "tier": tier, "arm": arm, "trial": sim.get("trial", 0),
        "rule_id": score["rule_id"], "rule_type": rule["type"], "category": rule["category"],
        "triggered": score["triggered"], "adhered": score["adhered"], "reached": score["reached"],
        "false_trigger": score["false_trigger"], "control_correct": score["control_correct"],
        "task_pass": int((sim.get("reward_info") or {}).get("reward") == 1),
        "termination": sim.get("termination_reason"),
        "rule_position": position, "position_tercile": tercile,
        "retrieval_calls": n_retr, "rule_doc_retrieved": retrieved, "rule_docs_all_retrieved": all_retrieved,
        **{f"{k}_tokens": tok[k] for k in ("input", "cache_read", "cache_write", "output")},
        "cost": round(cost, 5),
    }


def mean(xs):
    xs = [x for x in xs if x is not None and x != ""]
    return sum(xs) / len(xs) if xs else None


def cluster_ci(rows, key, rng):
    """95% CI of the run-level mean of `key`, resampling rules with replacement."""
    by_rule = defaultdict(list)
    for r in rows:
        if r[key] is not None and r[key] != "":
            by_rule[r["rule_id"]].append(r[key])
    ids = sorted(by_rule)
    if not ids:
        return None, None
    stats = []
    for _ in range(N_BOOT):
        vals = [v for i in (rng.choice(ids) for _ in ids) for v in by_rule[i]]
        stats.append(sum(vals) / len(vals))
    stats.sort()
    return stats[int(0.025 * N_BOOT)], stats[int(0.975 * N_BOOT) - 1]


def pass_hat_k(rows, k):
    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task_id"]].append(r["task_pass"])
    vals = [math.comb(sum(v), k) / math.comb(len(v), k) for v in by_task.values() if len(v) >= k]
    return mean(vals)


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def r3(x):
    return "" if x is None else round(x, 3)


def write_csv(name, rows):
    if not rows:
        return
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", default="pilot")
    p.add_argument("--extra", nargs="*", default=[], help="ARM=BATCH, e.g. jitprompt_action=action")
    args = p.parse_args()
    extra = dict(e.split("=", 1) for e in args.extra)

    rules = {k: v for k, v in load_rules().items() if not v.get("dropped")}
    tasks = {t["id"]: t for t in json.loads((REPO / "jitprompt_rules/tasks_rules.json").read_text())}
    manifest = json.loads((ROOT / "data/tiers/manifest.json").read_text())
    jp_maps = {}
    for t in TIERS:
        sp = ROOT / f"results/jitprompt/snapshot_{t}.json"
        if sp.exists():
            jp_maps[t] = {v["jp_id"][:8]: k for k, v in json.loads(sp.read_text())["documents"].items()}
    active = set(TASK_IDS)

    runs = []
    for arm, tier, name in cells(args.batch, extra):
        for sim in load(name):
            if sim["task_id"] in active:
                runs.append(run_row(sim, arm, tier, rules, tasks, manifest, jp_maps))
    OUT.mkdir(exist_ok=True)
    write_csv("runs.csv", runs)

    rng = random.Random(0)
    groups = defaultdict(list)
    for r in runs:
        groups[(r["tier"], r["arm"])].append(r)
    order = [(t, a) for t in TIERS for a in ARMS + list(extra)] + [("ref", r) for r in REFS]
    summary = []
    for key in order:
        rows = groups.get(key, [])
        if not rows:
            continue
        trig = [r for r in rows if r["triggered"] == 1]
        ctl = [r for r in rows if r["triggered"] == 0]
        reached = [r for r in trig if r["reached"] == 1]
        lo, hi = cluster_ci(trig, "adhered", rng)
        flo, fhi = cluster_ci(ctl, "false_trigger", rng)
        summary.append({
            "tier": key[0], "arm": key[1], "n_triggered_runs": len(trig), "n_control_runs": len(ctl),
            "adherence": r3(mean([r["adhered"] for r in trig])), "adherence_ci_lo": r3(lo), "adherence_ci_hi": r3(hi),
            "adherence_given_reached": r3(mean([r["adhered"] for r in reached])), "reached_rate": r3(len(reached) / len(trig)) if trig else "",
            "false_trigger_rate": r3(mean([r["false_trigger"] for r in ctl])), "false_trigger_ci_lo": r3(flo), "false_trigger_ci_hi": r3(fhi),
            "control_correct": r3(mean([r["control_correct"] for r in ctl])),
            "task_pass": r3(mean([r["task_pass"] for r in rows])), "pass_hat_2": r3(pass_hat_k(rows, 2)),
            "rule_doc_retrieved": r3(mean([r["rule_doc_retrieved"] for r in trig])),
            "retrieval_calls": r3(mean([r["retrieval_calls"] for r in rows])),
            "cost_per_run": r3(mean([r["cost"] for r in rows])), "cost_total": r3(sum(r["cost"] for r in rows)),
        })
    write_csv("summary.csv", summary)

    # Paired McNemar on (task, trial) of triggered runs.
    trig_idx = {(r["tier"], r["arm"], r["task_id"], r["trial"]): r["adhered"] for r in runs if r["triggered"] == 1}
    comparisons = [("XL", "jitprompt", "XL", "full_prompt", True)]
    for t in TIERS:
        comparisons += [(t, "jitprompt", t, "rag_bm25", False), (t, "rag_bm25", t, "full_prompt", False)]
    comparisons += [("S", "jitprompt", "S", "full_prompt", False)]
    comparisons += [("S", a, "XL", a, False) for a in ARMS]
    for a in extra:  # pre-registered for the extra arm: vs each main arm at XL
        comparisons += [("XL", a, "XL", b, False) for b in ARMS]
    paired = []
    for ta, a, tb, b, primary in comparisons:
        keys = {(k[2], k[3]) for k in trig_idx if k[:2] == (ta, a)} & {(k[2], k[3]) for k in trig_idx if k[:2] == (tb, b)}
        pa = [trig_idx[(ta, a, *k)] for k in sorted(keys)]
        pb = [trig_idx[(tb, b, *k)] for k in sorted(keys)]
        only_a = sum(x == 1 and y == 0 for x, y in zip(pa, pb))
        only_b = sum(x == 0 and y == 1 for x, y in zip(pa, pb))
        paired.append({
            "comparison": f"{a}@{ta} vs {b}@{tb}", "primary": int(primary), "n_pairs": len(keys),
            "adherence_a": r3(mean(pa)), "adherence_b": r3(mean(pb)), "diff": r3((mean(pa) or 0) - (mean(pb) or 0)) if keys else "",
            "only_a": only_a, "only_b": only_b, "both": sum(x == 1 and y == 1 for x, y in zip(pa, pb)),
            "neither": sum(x == 0 and y == 0 for x, y in zip(pa, pb)), "mcnemar_p": r3(mcnemar_exact(only_a, only_b)),
        })
    write_csv("paired.csv", paired)

    by_type = []
    types = sorted({r["rule_type"] for r in runs})
    for key in order:
        for ty in types:
            rows = [r for r in groups.get(key, []) if r["rule_type"] == ty]
            if rows:
                by_type.append({"tier": key[0], "arm": key[1], "rule_type": ty,
                                "adherence": r3(mean([r["adhered"] for r in rows if r["triggered"] == 1])),
                                "false_trigger_rate": r3(mean([r["false_trigger"] for r in rows if r["triggered"] == 0])),
                                "n_triggered_runs": sum(r["triggered"] == 1 for r in rows)})
    write_csv("by_type.csv", by_type)

    by_pos = []
    for t in TIERS:
        for terc in (1, 2, 3):
            rows = [r for r in groups.get((t, "full_prompt"), []) if r["triggered"] == 1 and r["position_tercile"] == terc]
            by_pos.append({"tier": t, "position_tercile": terc, "n_triggered_runs": len(rows),
                           "adherence": r3(mean([r["adhered"] for r in rows]))})
    write_csv("by_position.csv", by_pos)

    ref_miss = {(r["task_id"], r["trial"]) for r in groups.get(("ref", "required_docs"), []) if r["triggered"] == 1 and r["adhered"] == 0}
    ref_miss_task = {k[0] for k in ref_miss}
    attribution = []
    for r in runs:
        if r["arm"] in ("rag_bm25", "jitprompt") and r["triggered"] == 1 and r["adhered"] == 0:
            attribution.append({"tier": r["tier"], "arm": r["arm"], "task_id": r["task_id"], "trial": r["trial"],
                                "rule_id": r["rule_id"], "rule_type": r["rule_type"], "reached": r["reached"],
                                "failure": "attention_miss" if r["rule_doc_retrieved"] else "retrieval_miss",
                                "task_hard": int(r["task_id"] in ref_miss_task)})
    write_csv("attribution.csv", attribution)

    print(f"{'tier':4} {'arm':14}{'adh':>6} {'95% CI':>13}{'adh|reached':>12}{'FT':>6}{'pass':>6}{'ruledoc':>8}{'$/run':>7}")
    for s in summary:
        print(f"{s['tier']:4} {s['arm']:14}{s['adherence']:>6} [{s['adherence_ci_lo']}, {s['adherence_ci_hi']}]"
              f"{s['adherence_given_reached']:>12}{s['false_trigger_rate']:>6}{s['task_pass']:>6}{s['rule_doc_retrieved']:>8}{s['cost_per_run']:>7}")
    print()
    for pr in paired:
        print(f"{'PRIMARY ' if pr['primary'] else '        '}{pr['comparison']:34} n={pr['n_pairs']:3} "
              f"{pr['adherence_a']} vs {pr['adherence_b']}  ({pr['only_a']}-{pr['only_b']})  p={pr['mcnemar_p']}")
    att = defaultdict(int)
    for a in attribution:
        att[(a["tier"], a["arm"], a["failure"])] += 1
    print("\nmisses:", dict(sorted(att.items())))
    print(f"wrote {OUT}/runs.csv summary.csv paired.csv by_type.csv by_position.csv attribution.csv")


if __name__ == "__main__":
    main()
