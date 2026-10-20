"""Deterministic rule-adherence scoring from a tool-call trajectory (no LLM judge).

    uv run --no-sync python jitprompt_rules/check_rules.py data/simulations/<save_to>/results.json

A trajectory is the ordered list of the agent's tool calls, attempted ones included (a call
that returned an error still counts: the agent took the action). Discoverable tools are
unwrapped: call_discoverable_agent_tool(agent_tool_name=X, arguments='<json>') counts as a
call to X with those arguments.

Per rules.yaml:
- triggered task: adhered = all `required` matched, no `forbidden` matched, every `order`
  pair [A, B] has a call matching A before the first call matching B.
- control task: false_trigger = any `false_trigger` pattern matched;
  control_correct = all `required` matched and no false trigger.
- both: reached = any call to a `decision` tool (the agent got to the rule's decision point).
"""

import json
import sys
from pathlib import Path

import yaml

RULES_YAML = Path(__file__).resolve().parent / "rules.yaml"
TOL = 0.005


def load_rules() -> dict[str, dict]:
    return {r["id"]: r for r in yaml.safe_load(RULES_YAML.read_text())}


def unwrap(name: str, arguments) -> tuple[str, dict]:
    args = arguments if isinstance(arguments, dict) else _loads(arguments)
    if name == "call_discoverable_agent_tool":
        inner = args.get("arguments", {})
        return args.get("agent_tool_name", ""), inner if isinstance(inner, dict) else _loads(inner)
    return name, args


def _loads(s) -> dict:
    try:
        v = json.loads(s) if isinstance(s, str) else {}
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _equal(expected, actual) -> bool:
    if isinstance(expected, bool):
        return actual is expected or str(actual).strip().lower() == str(expected).lower()
    if isinstance(expected, (int, float)):
        a = _num(actual)
        return a is not None and abs(a - expected) <= TOL
    return str(actual).strip() == str(expected)


def matches(pattern: dict, call: tuple[str, dict]) -> bool:
    name, args = call
    if name != pattern["tool"]:
        return False
    return all(k in args and _equal(v, args[k]) for k, v in (pattern.get("args") or {}).items())


def first_index(pattern: dict, calls: list) -> int | None:
    return next((i for i, c in enumerate(calls) if matches(pattern, c)), None)


def score_calls(rule: dict, kind: str, raw_calls: list[dict]) -> dict:
    """raw_calls: [{'name':..., 'arguments':...}] in order. Returns the per-run rule scores."""
    calls = [unwrap(c["name"], c.get("arguments")) for c in raw_calls]
    reached = int(any(name in rule["decision"] for name, _ in calls))
    if kind == "triggered":
        chk = rule["check"]
        required = all(first_index(p, calls) is not None for p in chk.get("required", []))
        forbidden = any(first_index(p, calls) is not None for p in chk.get("forbidden", []))
        order_ok = True
        for a, b in chk.get("order", []):
            ia, ib = first_index(a, calls), first_index(b, calls)
            order_ok &= ia is not None and ib is not None and ia < ib
        adhered = int(required and not forbidden and order_ok)
        return {"rule_id": rule["id"], "triggered": 1, "adhered": adhered, "reached": reached,
                "required_met": int(required), "forbidden_hit": int(forbidden), "order_ok": int(order_ok),
                "false_trigger": None, "control_correct": None}
    chk = rule["check_control"]
    required = all(first_index(p, calls) is not None for p in chk.get("required", []))
    false_trigger = any(first_index(p, calls) is not None for p in chk.get("false_trigger", []))
    return {"rule_id": rule["id"], "triggered": 0, "adhered": None, "reached": reached,
            "required_met": int(required), "forbidden_hit": None, "order_ok": None,
            "false_trigger": int(false_trigger), "control_correct": int(required and not false_trigger)}


def calls_from_simulation(sim: dict) -> list[dict]:
    """Agent tool calls, in order, from a tau2 simulation record (results.json)."""
    out = []
    for m in sim.get("messages", []):
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                out.append({"name": tc.get("name"), "arguments": tc.get("arguments")})
    return out


def parse_task_id(task_id: str) -> tuple[str, str]:
    """task_R07_t -> ('R07', 'triggered')."""
    _, rid, k = task_id.split("_")
    return rid, {"t": "triggered", "c": "control"}[k]


def score_simulation(sim: dict, rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    rid, kind = parse_task_id(sim["task_id"])
    return {"task_id": sim["task_id"], "trial": sim.get("trial"),
            **score_calls(rules[rid], kind, calls_from_simulation(sim))}


if __name__ == "__main__":
    rules = load_rules()
    for path in sys.argv[1:]:
        for sim in json.loads(Path(path).read_text())["simulations"]:
            print(json.dumps(score_simulation(sim, rules)))
