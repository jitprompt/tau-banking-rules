"""Build the planted-rule corpus and tasks from rules.yaml.

    uv run --no-sync python jitprompt_rules/build_rules.py [--validate]

Writes (all under jitprompt_rules/, originals untouched):
- rule_docs/<id>.json         rule-bearing docs: new standalone docs, and buried copies
                              (original content + appended section, same id)
- tasks_rules.json            the 48 tasks in tau2's task schema (list)
- tasks/task_R##_{t,c}.json   one file per task, the layout upstream's loader globs

--validate replays each task's golden actions on a fresh environment (as tau2's evaluator
does) and fails on any tool error, then scores the golden trajectories with check_rules.py:
triggered gold must adhere, control gold must not false-trigger, and each gold must fail
the other kind's check (so the two tasks really differ on the rule).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DOMAIN = REPO / "data/tau2/domains/banking_knowledge"
ORIGINAL_DOCS = DOMAIN / "documents"
RULE_DOCS = HERE / "rule_docs"
TASKS_DIR = HERE / "tasks"
TASKS_JSON = HERE / "tasks_rules.json"
RULES_YAML = HERE / "rules.yaml"

TIME_VERIFIED = "2025-11-14 03:40:00 EST"
# Agent tools callable directly; everything else is a discoverable tool (unlock + call).
BASE_TOOLS = {
    "transfer_to_human_agents", "get_current_time", "get_user_information_by_id",
    "get_user_information_by_name", "get_user_information_by_email", "change_user_email",
    "get_referrals_by_user", "get_credit_card_transactions_by_user",
    "get_credit_card_accounts_by_user", "log_verification",
}
KINDS = {"triggered": "t", "control": "c"}


def load_rules() -> list[dict]:
    return yaml.safe_load(RULES_YAML.read_text())


def load_db() -> dict:
    return json.loads((DOMAIN / "db.json").read_text())


def task_id(rule_id: str, kind: str) -> str:
    return f"task_{rule_id}_{KINDS[kind]}"


# ---------------------------------------------------------------- docs

def build_docs(rules: list[dict]) -> dict[str, dict]:
    """Rule-bearing docs keyed by id. Buried docs: original + `## section` appended."""
    out: dict[str, dict] = {}
    for rule in rules:
        for d in rule["docs"]:
            if d["placement"] == "standalone":
                assert not (ORIGINAL_DOCS / f"{d['id']}.json").exists(), f"{d['id']} exists upstream"
                doc = {"id": d["id"], "title": d["title"], "content": d["text"].strip() + "\n"}
            else:
                orig = json.loads((ORIGINAL_DOCS / f"{d['id']}.json").read_text())
                doc = {**orig, "content": orig["content"].rstrip() + f"\n\n## {d['section']}\n\n" + d["text"].strip() + "\n"}
            assert d["id"] not in out, f"doc {d['id']} used by two rules"
            out[d["id"]] = doc
    return out


def rule_doc_ids(rule: dict, kind_spec: dict | None = None) -> list[str]:
    if kind_spec and kind_spec.get("rule_docs"):
        return list(kind_spec["rule_docs"])
    return [d["id"] for d in rule["docs"]]


# ---------------------------------------------------------------- tasks

def expand_setup(setup: dict, user: dict) -> dict:
    """agent_data for initial_state: raw table dicts plus the `payments` helper."""
    setup = json.loads(json.dumps(setup or {}).replace("__ADDRESS__", user["address"]))
    payments = setup.pop("payments", None)
    if payments:
        rows = setup.setdefault("payment_history", {"data": {}})["data"]
        for acct, months in payments.items():
            for i in range(months):  # monthly on-time payments, most recent 10/15/2025
                y, m = 2025, 10 - i
                while m <= 0:
                    y, m = y - 1, m + 12
                pid = f"pay_{acct.removeprefix('cc_')}_{y}{m:02d}"
                rows[pid] = {"payment_id": pid, "credit_card_account_id": acct, "user_id": user["user_id"],
                             "payment_date": f"{m:02d}/15/{y}", "amount": "$250.00", "status": "ON_TIME"}
    return setup or None


def expand_actions(actions: list, user: dict, tid: str) -> list[dict]:
    out, unlocked = [], set()

    def add(name, arguments, extra=None):
        out.append({"action_id": f"{tid}_{len(out)}", "requestor": "assistant", "name": name,
                    "arguments": arguments, **(extra or {})})

    for a in actions:
        if a == "verify":
            add("log_verification", {"name": user["name"], "user_id": user["user_id"], "address": user["address"],
                                     "email": user["email"], "phone_number": user["phone_number"],
                                     "date_of_birth": user["date_of_birth"], "time_verified": TIME_VERIFIED})
            continue
        tool, args, *extra = a
        args = json.loads(json.dumps(args).replace("__ADDRESS__", user["address"]))
        if tool in BASE_TOOLS:
            add(tool, args, extra[0] if extra else None)
        else:
            if tool not in unlocked:
                add("unlock_discoverable_agent_tool", {"agent_tool_name": tool})
                unlocked.add(tool)
            add("call_discoverable_agent_tool", {"agent_tool_name": tool, "arguments": json.dumps(args)})
    return out


def user_instructions(script: dict, user: dict) -> str:
    info = [f"- Your full name: {user['name']}", f"- Your phone number: {user['phone_number']}",
            f"- Your email: {user['email']}", f"- Your date of birth: {user['date_of_birth']}",
            f"- Your address: {user['address']}"]
    flow = [f'1. **Opening:** "{script["opening"]}"',
            "2. **Provide verification info when asked:** Give the details listed above as requested."]
    flow += [f"{i}. {line}" for i, line in enumerate(script.get("flow", []), start=3)]
    return "\n".join([
        f"**Your character:** {script['character']}", "",
        f"**Your situation:** {script['situation']}", "",
        f"**Your goal:** {script['goal']}", "",
        "**Information you know and should provide when asked:**", *info, "",
        "You do not know Rho-Bank's internal policies; do not suggest specific amounts, limits or procedures "
        "beyond what is described here.", "",
        "## Conversation Flow:", "", *flow,
    ])


def build_task(rule: dict, kind: str, users: dict) -> dict:
    spec = rule["tasks"][kind]
    user = users[str(spec["user"])]
    tid = task_id(rule["id"], kind)
    required = list(dict.fromkeys(rule_doc_ids(rule, spec) + list(spec.get("docs", []))))
    notes = (f"{rule['id']} ({rule['type']}), {kind} task. Trigger: {rule['trigger']}. "
             + ("The rule applies here; the golden actions follow it."
                if kind == "triggered" else "The rule nearly applies but does not; applying it is wrong."))
    return {
        "id": tid,
        "description": {"purpose": f"Planted rule {rule['id']} ({kind})", "relevant_policies": None, "notes": notes},
        "user_scenario": {"persona": None, "instructions": user_instructions(spec["script"], user)},
        "initial_state": {"initialization_data": {"agent_data": expand_setup(spec.get("setup"), user), "user_data": None},
                          "initialization_actions": None, "message_history": None},
        "evaluation_criteria": {"actions": expand_actions(spec["actions"], user, tid),
                                "reward_basis": spec.get("reward_basis", ["DB"])},
        "annotations": None,
        "user_tools": [],
        "required_documents": required,
    }


def build_all() -> tuple[list[dict], dict[str, dict], list[dict]]:
    rules = load_rules()
    users = load_db()["users"]["data"]
    docs = build_docs(rules)
    tasks = [build_task(r, k, users) for r in rules for k in KINDS]
    return rules, docs, tasks


def write(docs: dict, tasks: list[dict]):
    RULE_DOCS.mkdir(exist_ok=True)
    for old in RULE_DOCS.glob("*.json"):
        old.unlink()
    for doc_id, doc in docs.items():
        (RULE_DOCS / f"{doc_id}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    TASKS_DIR.mkdir(exist_ok=True)
    for old in TASKS_DIR.glob("task_*.json"):
        old.unlink()
    for t in tasks:
        (TASKS_DIR / f"{t['id']}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
    TASKS_JSON.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- validation

def replay(task: dict) -> tuple[list[str], list[dict]]:
    """Replay golden actions on a fresh env; return (errors, tool-call trajectory for check_rules)."""
    from tau2.data_model.tasks import Task
    from tau2.domains.banking_knowledge import environment as bk_env
    from tau2.runner.build import _derive_read_log_allowlist

    t = Task.model_validate(task)
    env = bk_env.get_environment(retrieval_variant="no_knowledge",
                                 read_log_allowlist=_derive_read_log_allowlist(t))
    env.set_state(initialization_data=t.initial_state.initialization_data,
                  initialization_actions=None, message_history=[])
    errors, calls = [], []
    for a in t.evaluation_criteria.actions:
        out = str(env.make_tool_call(tool_name=a.name, requestor=a.requestor, **a.arguments))
        if out.lower().startswith("error") or "error:" in out.lower()[:200]:
            errors.append(f"{a.name}({a.arguments}) -> {out[:200]}")
        calls.append({"name": a.name, "arguments": a.arguments})
    return errors, calls


def validate(rules: list[dict], tasks: list[dict]) -> bool:
    sys.path.insert(0, str(REPO))
    from jitprompt_rules.check_rules import score_calls

    by_id = {t["id"]: t for t in tasks}
    ok = True
    for rule in rules:
        res = {}
        for kind in KINDS:
            errors, calls = replay(by_id[task_id(rule["id"], kind)])
            for e in errors:
                print(f"  {rule['id']} {kind}: TOOL ERROR {e}")
                ok = False
            res[kind] = calls
        t_on_t = score_calls(rule, "triggered", res["triggered"])
        c_on_c = score_calls(rule, "control", res["control"])
        t_on_c = score_calls(rule, "triggered", res["control"])   # control gold scored as triggered
        c_on_t = score_calls(rule, "control", res["triggered"])   # triggered gold scored as control
        checks = {
            "triggered gold adheres": t_on_t["adhered"] == 1,
            "control gold correct": c_on_c["control_correct"] == 1 and c_on_c["false_trigger"] == 0,
            "control gold fails triggered check": t_on_c["adhered"] == 0,
            "triggered gold fails control check": c_on_t["control_correct"] == 0,
        }
        bad = [k for k, v in checks.items() if not v]
        print(f"{rule['id']:4} {rule['type']:15} {'OK' if not bad else 'FAIL: ' + '; '.join(bad)}")
        ok &= not bad
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--validate", action="store_true")
    args = p.parse_args()
    rules, docs, tasks = build_all()
    write(docs, tasks)
    n_stand = sum(d["placement"] == "standalone" for r in rules for d in r["docs"])
    print(f"{len(rules)} rules, {len(docs)} rule docs ({n_stand} standalone, {len(docs) - n_stand} buried), "
          f"{len(tasks)} tasks -> {TASKS_DIR.relative_to(REPO)}")
    if args.validate:  # replay needs only tools + DB, so the KB loaded here doesn't matter
        sys.exit(0 if validate(rules, tasks) else 1)


if __name__ == "__main__":
    main()
