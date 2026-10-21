"""`jitprompt_action`: the jitprompt arm plus action-indexed retrieval (a pre-call hook).

Prototype of action-indexed retrieval, design frozen before any run.

The agent sees exactly the jitprompt arm (same prompt, same three MCP tools, same namespace).
In addition, every state-mutating discoverable tool call passes through a hook:
- Index: the tier's docs, split at `## ` headings (a local stand-in for jitprompt's ingest).
- Terms for a call: the tool name (weight 2); string argument values that look like enums
  (snake_case or UPPERCASE; weight 1); argument keys that are not generic ids or amounts
  (weight 1). Literal substring matching only.
- Candidates: sections scoring >= 2, best first, at most MAX_SECTIONS within MAX_CHARS,
  skipping sections the agent already saw (in jitprompt output or earlier hook output).
- If any remain, the call is NOT executed (no DB effect) and the agent receives them with an
  instruction to call again if the call complies. Otherwise the call runs unchanged.
Each check is logged to results/retrieval_calls.jsonl as tool `action_check`.
"""

import json
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tau2.domains.banking_knowledge import retrieval
from tau2.environment.toolkit import MUTATES_STATE_ATTR, ToolType, is_tool

from jitprompt_rules.variants import CALL_LOG, PROMPT, TOOLKITS, KnowledgeToolsJitprompt, _log_lock, _tier

ROOT = Path(__file__).resolve().parents[2]
MAX_SECTIONS = 3
MAX_CHARS = 10_000  # ~2.5K tokens
GENERIC_KEYS = {
    "user_id", "account_id", "credit_card_account_id", "card_id", "amount", "reason",
    "source_account_id", "destination_account_id", "shipping_address", "transaction_id",
    "checking_account_id", "full_name", "phone", "email", "address", "summary",
}
ENUM = re.compile(r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z]{3,})$")


def _norm(text: str) -> str:
    return " ".join(text.split())


@lru_cache(maxsize=4)
def section_index(tier: str) -> list[dict]:
    sections = []
    for p in sorted((ROOT / "data/tiers" / tier).glob("*.json")):
        doc = json.loads(p.read_text())
        parts = re.split(r"(?m)^(?=## )", doc["content"])
        for i, part in enumerate(parts):
            body = part.strip()
            if not body:
                continue
            text = f"From: {doc['title']}  [{doc['id']}]\n\n{body}"
            sections.append({"key": f"{doc['id']}#{i}", "doc_id": doc["id"], "text": text,
                             "fingerprint": _norm(body)[:120]})
    return sections


def call_terms(tool: str, args: dict) -> list[tuple[str, int]]:
    terms = [(tool, 2)]
    for k, v in args.items():
        if k not in GENERIC_KEYS:
            terms.append((k, 1))
        if isinstance(v, str) and ENUM.match(v):
            terms.append((v, 1))
    return terms


def governing_sections(tier: str, tool: str, args: dict, seen: list[str]) -> list[dict]:
    terms = call_terms(tool, args)
    seen_text = _norm("\n".join(seen))
    scored = []
    for s in section_index(tier):
        score = sum(w for t, w in terms if t in s["text"])
        if score >= 2 and s["fingerprint"] not in seen_text:
            scored.append((-score, len(s["text"]), s["key"], s))
    out, used = [], 0
    for *_, s in sorted(scored):
        if len(out) == MAX_SECTIONS or used + len(s["text"]) > MAX_CHARS:
            break
        out.append(s)
        used += len(s["text"])
    return out


class KnowledgeToolsJitpromptAction(KnowledgeToolsJitprompt):
    def __init__(self, db, task_id: Optional[str] = None):
        super().__init__(db, task_id=task_id)
        self._jb_seen_text: list[str] = []
        self._hook_lock = threading.Lock()

    @is_tool(ToolType.WRITE)
    def call_discoverable_agent_tool(self, agent_tool_name: str, arguments: str = "{}") -> str:
        """Call an agent discoverable tool that you have previously unlocked.

        Use this after unlocking a tool with `unlock_discoverable_agent_tool`. The knowledge base
        will tell you which tool to use and what arguments to provide.

        Args:
            agent_tool_name: The name of the agent discoverable tool to call
            arguments: JSON string of arguments for the tool (e.g., '{"user_id": "abc123"}')

        Returns:
            The result of executing the agent tool
        """
        method = self.get_discoverable_tools().get(agent_tool_name) if self.has_discoverable_tool(agent_tool_name) else None
        unlocked = agent_tool_name in self._agent_discoverable_tools_state
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
        except (json.JSONDecodeError, TypeError):
            args = None
        if method is not None and unlocked and isinstance(args, dict) and getattr(method, MUTATES_STATE_ATTR, False):
            tier = _tier()
            with self._hook_lock:
                found = governing_sections(tier, agent_tool_name, args, self._jb_seen_text)
                self._log(agent_tool_name, args, found)
                if found:
                    text = "\n\n---\n\n".join(s["text"] for s in found)
                    message = (f"Not executed yet. These instructions govern {agent_tool_name} with these arguments. "
                               f"Read them; if the call complies, call {agent_tool_name} again (adjust the arguments "
                               f"or take the required steps first if it does not).\n\n{text}")
                    self._jb_seen_text.append(message)
                    return message
        return super().call_discoverable_agent_tool(agent_tool_name, arguments)

    def _log(self, tool: str, args: dict, found: list[dict]):
        row = {"t": time.time(), "tier": _tier(), "arm": os.environ.get("JB_ARM"), "batch": os.environ.get("JB_BATCH"),
               "task_id": self._jb_task_id, "env_instance": self._jb_instance, "tool": "action_check",
               "args": {"tool": tool, "arguments": args}, "blocked": bool(found),
               "output_chars": sum(len(s["text"]) for s in found), "docs": [s["doc_id"] for s in found],
               "sections": [s["key"] for s in found]}
        with _log_lock, CALL_LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")


TOOLKITS["jitprompt_action"] = KnowledgeToolsJitpromptAction
retrieval.RETRIEVAL_VARIANTS["jitprompt_action"] = retrieval.RetrievalVariant(
    name="jitprompt_action", prompt_template=PROMPT, build_prompt=retrieval.standard_prompt,
)


# Grading replays the agent's tool calls on a fresh environment and, by default, aborts if a
# mutating call returns different text than it did live. The hook's output depends on what the
# agent saw from jitprompt earlier, which the replay doesn't reconstruct, so for this arm only
# the replay runs non-strict. Adherence is scored from the live transcript and is unaffected;
# task pass can be off where the replayed hook blocks a call the live one let through.
if os.environ.get("JB_ARM") == "jitprompt_action":
    import functools

    import tau2.runner.simulation as _sim

    _sim.evaluate_simulation = functools.partial(_sim.evaluate_simulation, strict_replay=False)
