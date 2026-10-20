"""Gate 2 rule-validity table.

    uv run --no-sync python jitprompt_rules/gate2_report.py [--sonnet jr_g2sonnet_required_docs] [--norules jr_g2haiku_no_rules]

Per rule: Sonnet with gold docs on the triggered task (adhered? reached?) and the control
(correct? false trigger?), plus Haiku with the rule text removed on the triggered task
(adhered by chance?). Verdicts:
- AMBIGUOUS  Sonnet misses the triggered rule or false-triggers on the control (fix or drop)
- WEAK       Haiku complies without the rule (re-run once before fixing; >20% is the bar)
- ok
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_rules import load_rules, score_simulation  # noqa: E402

SIMS = Path(__file__).resolve().parents[1] / "data/simulations"


def load(name: str) -> dict[str, list[dict]]:
    path = SIMS / name / "results.json"
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    rules = load_rules()
    for sim in json.loads(path.read_text())["simulations"]:
        row = score_simulation(sim, rules)
        row["reward"] = sim["reward_info"]["reward"] if sim.get("reward_info") else None
        row["termination"] = sim.get("termination_reason")
        out.setdefault(sim["task_id"], []).append(row)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sonnet", default="jr_g2sonnet_required_docs")
    p.add_argument("--norules", default="jr_g2haiku_no_rules")
    args = p.parse_args()
    son, nor = load(args.sonnet), load(args.norules)
    rules = load_rules()
    print(f"{'rule':5}{'type':15}{'S trig adh':>11}{'reached':>8}{'S ctl ok':>9}{'S ctl FT':>9}"
          f"{'S pass t/c':>11}{'H norules adh':>14}  verdict")
    ok = 0
    for rid, rule in rules.items():
        t = son.get(f"task_{rid}_t", [])
        c = son.get(f"task_{rid}_c", [])
        n = nor.get(f"task_{rid}_t", [])
        f = lambda rows, k: "/".join(str(r[k]) for r in rows) if rows else "-"  # noqa: E731
        ambiguous = any(r["adhered"] == 0 for r in t) or any(r["false_trigger"] == 1 for r in c)
        weak = any(r["adhered"] == 1 for r in n)
        verdict = "AMBIGUOUS" if ambiguous else ("WEAK" if weak else "ok")
        if not t or not c or not n:
            verdict = "incomplete"
        ok += verdict == "ok"
        print(f"{rid:5}{rule['type']:15}{f(t, 'adhered'):>11}{f(t, 'reached'):>8}{f(c, 'control_correct'):>9}"
              f"{f(c, 'false_trigger'):>9}{f(t, 'reward') + ' ' + f(c, 'reward'):>11}{f(n, 'adhered'):>14}  {verdict}")
    print(f"\n{ok}/{len(rules)} rules ok")


if __name__ == "__main__":
    main()
