"""`tau2` CLI with the benchmark's patches applied. Upstream files stay untouched.

    JB_TIER=S JB_ARM=full_prompt uv run python -m jitprompt_rules.tau2_entry run --domain banking_knowledge ...

Patches (all recorded in DEVIATIONS.md):
- registers `anthropic/claude-haiku-5-5` and `anthropic/claude-sonnet-5-5` with LiteLLM (missing from the pinned 1.81.11 model map);
- loads the knowledge base from `data/tiers/<JB_TIER>` when JB_TIER is set, in sorted id order
  so the full_kb prompt is byte-identical across runs (upstream uses unsorted glob order);
- wraps every LLM call: budget hard stop before the call, raw usage + cost to the ledger after;
- registers the `jitprompt` retrieval variant (see variants.py);
- loads tasks from jitprompt_rules/tasks/ and the DB from jitprompt_rules/db_rules.json if it exists.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

import litellm  # noqa: E402

import tau2.utils.llm_utils as llm_utils  # noqa: E402
from tau2.domains.banking_knowledge import environment as bk_env  # noqa: E402
from tau2.domains.banking_knowledge.data_model import KnowledgeBase  # noqa: E402

from jitprompt_rules.cost import Ledger  # noqa: E402

TIERS_DIR = REPO.parent / "data/tiers"

litellm.register_model({
    "anthropic/claude-sonnet-5-5": {
        "litellm_provider": "anthropic",
        "mode": "chat",
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 128_000,
        "input_cost_per_token": 2.00e-6,
        "output_cost_per_token": 10.00e-6,
        "cache_read_input_token_cost": 0.20e-6,
        "cache_creation_input_token_cost": 2.50e-6,
        "supports_function_calling": True,
        "supports_tool_choice": True,
        "supports_prompt_caching": True,
        "supports_reasoning": True,
        "supports_system_messages": True,
    },
    "anthropic/claude-haiku-5-5": {
        "litellm_provider": "anthropic",
        "mode": "chat",
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 128_000,
        # ≤100K-token rates; the ledger (cost.py) applies the >100K tier itself.
        "input_cost_per_token": 0.10e-6,
        "output_cost_per_token": 0.50e-6,
        "cache_read_input_token_cost": 0.01e-6,
        "cache_creation_input_token_cost": 0.125e-6,
        "supports_function_calling": True,
        "supports_tool_choice": True,
        "supports_prompt_caching": True,
        "supports_reasoning": True,
        "supports_system_messages": True,
    }
})


def _load_kb() -> KnowledgeBase:
    tier = os.environ.get("JB_TIER")
    kb = KnowledgeBase.load(str(TIERS_DIR / tier if tier else bk_env.KNOWLEDGE_DOCUMENTS_DIR))
    if tier and not kb.documents:
        raise RuntimeError(f"no documents for tier {tier} in {TIERS_DIR / tier}")
    return KnowledgeBase(documents=dict(sorted(kb.documents.items())))


bk_env.get_knowledge_base = _load_kb

# Rule-benchmark tasks (one task_*.json per task, emitted by build_tasks.py) and, if present,
# the run's own db.json copy. Both are module globals read at call time by upstream loaders.
RULES_DIR = Path(__file__).resolve().parent
bk_env.KNOWLEDGE_TASK_SET_PATH = RULES_DIR / "tasks"
if (RULES_DIR / "db_rules.json").exists():
    bk_env.KNOWLEDGE_DB_PATH = RULES_DIR / "db_rules.json"

ledger = Ledger()
_labels = {k: os.environ.get(f"JB_{k.upper()}") for k in ("tier", "arm", "batch")}
_completion = llm_utils.completion


def _role(messages: list[dict]) -> str:
    system = next((m.get("content") for m in messages if m.get("role") == "system"), "") or ""
    return "agent" if "<policy>" in str(system) else "user"


def _tracked_completion(*args, **kwargs):
    ledger.check()
    response = _completion(*args, **kwargs)
    model = kwargs.get("model") or (args[0] if args else "claude-haiku-5-5")
    ledger.record(response.usage, model=model, role=_role(kwargs.get("messages", [])), **_labels)
    return response


llm_utils.completion = _tracked_completion

import jitprompt_rules.variants  # noqa: E402,F401  (registers the jitprompt variant)
import jitprompt_rules.action_hook  # noqa: E402,F401  (registers jitprompt_action)
import jitprompt_rules.pinned  # noqa: E402,F401  (registers jitprompt_pinned)
import jitprompt_rules.pins_server  # noqa: E402,F401  (registers jitprompt_sysprompt, jitprompt_inband)

from tau2.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "tau2"
    main()
