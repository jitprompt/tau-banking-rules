"""The `jitprompt` retrieval variant for banking_knowledge, registered at import.

The agent gets the base banking tools plus jitprompt's own three MCP tools
(get_toc, get_section, search_instructions). Their descriptions are taken
verbatim from the production server's tools/list at import, so the agent sees
exactly what any MCP client would. Every call goes to production jitprompt over
MCP (jitprompt_client.py) for the namespace of JB_TIER; nothing is reimplemented.

Each call is also appended to results/retrieval_calls.jsonl (task, tier, tool,
args, output size, latency, doc ids named in the output).
"""

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from tau2.domains.banking_knowledge import environment as bk_env
from tau2.domains.banking_knowledge import retrieval
from tau2.domains.banking_knowledge.tools import KnowledgeTools
from tau2.environment.toolkit import ToolKitType, ToolType, is_tool
from tau2.registry import registry

from jitprompt_rules.jitprompt_client import DEFAULT_CLIENT_NAME, PINS_HEADER, for_tier, new_client

ROOT = Path(__file__).resolve().parents[2]
CALL_LOG = ROOT / "results/retrieval_calls.jsonl"
PROMPT = Path(__file__).parent / "prompts/jitprompt.md"
DOC_REF = re.compile(r"\[doc ([0-9a-f]{8})\]")


ALSO_MATCHED = "Also matched, not shown"


def returned_part(text: str) -> str:
    """jitprompt ≥1.3 ends a search with documents that matched but were NOT returned
    ("Also matched, not shown …", same [doc …] tags); only the part before counts as retrieved."""
    i = text.find(ALSO_MATCHED)
    return text if i < 0 else text[:i]
_log_lock = threading.Lock()


def _tier() -> str:
    tier = os.environ.get("JB_TIER")
    if not tier:
        raise RuntimeError("the jitprompt variant needs JB_TIER")
    return tier


def _doc_map(tier: str) -> dict[str, str]:
    snap = json.loads((ROOT / f"results/jitprompt/snapshot_{tier}.json").read_text())
    return {v["jp_id"][:8]: k for k, v in snap["documents"].items()}


class JitpromptMixin(metaclass=ToolKitType):
    """jitprompt's MCP tools. Expects `self._jb_task_id`."""

    def _client(self, tier: str):
        """JB_JP_SESSION=conversation: one MCP session per conversation (this toolkit instance),
        named JB_JP_CLIENT_NAME; needed from jitprompt 1.3.1 on, which delivers pinned docs once
        per session. Otherwise the legacy per-thread client shared across conversations."""
        if os.environ.get("JB_JP_SESSION") != "conversation":
            return for_tier(tier)
        if getattr(self, "_jb_client", None) is None:
            self._jb_client = new_client(tier, os.environ.get("JB_JP_CLIENT_NAME", DEFAULT_CLIENT_NAME))
        return self._jb_client

    def _jitprompt(self, tool: str, arguments: dict) -> str:
        tier = _tier()
        start = time.perf_counter()
        client = self._client(tier)
        output = client.call_tool(tool, arguments)
        latency = time.perf_counter() - start
        doc_map = getattr(self, "_jb_doc_map", None) or {}
        row = {
            "t": time.time(), "tier": tier, "arm": os.environ.get("JB_ARM"), "batch": os.environ.get("JB_BATCH"),
            "task_id": getattr(self, "_jb_task_id", None), "env_instance": getattr(self, "_jb_instance", None),
            "tool": tool, "args": arguments, "latency_s": round(latency, 3), "output_chars": len(output),
            "docs": [doc_map.get(p, p) for p in DOC_REF.findall(returned_part(output))],
            "client_name": client.client_name, "session_id": client.session_id, "connects": client.connects,
            "server_version": (client.server_info.get("serverInfo") or {}).get("version"),
            "starts_with_pins": output.startswith(PINS_HEADER),
        }
        with _log_lock, CALL_LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")
        if hasattr(self, "_jb_seen_text"):  # read by action_hook to skip already-shown sections
            self._jb_seen_text.append(output)
        return output

    @is_tool(ToolType.READ)
    def get_toc(self, document_id: Optional[str] = None, query: Optional[str] = None) -> str:
        args = {k: v for k, v in (("document_id", document_id), ("query", query)) if v}
        return self._jitprompt("get_toc", args)

    @is_tool(ToolType.READ)
    def get_section(self, section_id: str) -> str:
        return self._jitprompt("get_section", {"section_id": section_id})

    @is_tool(ToolType.READ)
    def search_instructions(self, plan: str) -> str:
        return self._jitprompt("search_instructions", {"plan": plan})


SNAPSHOT_FOR_TOOLS = ROOT / "results/jitprompt/snapshot_S.json"


def _install_descriptions() -> bool:
    """Docstrings = the server's tool descriptions, so tau2 builds the same tool schema text.
    Returns False before the namespaces are snapshotted (Gate 3); the arm then refuses to run."""
    if not SNAPSHOT_FOR_TOOLS.exists():
        return False
    tools = {t["name"]: t for t in json.loads(SNAPSHOT_FOR_TOOLS.read_text())["tools"]}
    expected = {"get_toc", "get_section", "search_instructions"}
    if set(tools) != expected:
        raise RuntimeError(f"jitprompt tools changed: {sorted(tools)}")
    for name in expected:
        params = tools[name]["inputSchema"]["properties"]
        signature_params = set(getattr(JitpromptMixin, name).__code__.co_varnames[1:len(params) + 1])
        if signature_params != set(params):
            raise RuntimeError(f"{name}: server params {sorted(params)} != toolkit {sorted(signature_params)}")
        # tau2 (docstring_parser) treats the first line as the short description and
        # rejoins it with a blank line; unwrap the first paragraph so the text survives intact.
        first, _, rest = tools[name]["description"].strip().partition("\n\n")
        getattr(JitpromptMixin, name).__doc__ = " ".join(first.split()) + ("\n\n" + rest if rest else "")
    return True


_DESCRIPTIONS_INSTALLED = _install_descriptions()


class KnowledgeToolsJitprompt(JitpromptMixin, KnowledgeTools):
    def __init__(self, db, task_id: Optional[str] = None):
        super().__init__(db)
        self._jb_task_id = task_id
        self._jb_instance = uuid.uuid4().hex[:8]
        self._jb_doc_map = _doc_map(_tier())


retrieval.RETRIEVAL_VARIANTS["jitprompt"] = retrieval.RetrievalVariant(
    name="jitprompt", prompt_template=PROMPT, build_prompt=retrieval.standard_prompt,
)

_upstream_get_environment = registry.get_env_constructor("banking_knowledge")
_upstream_build_tools = bk_env.build_tools
_current_task = threading.local()


# variant name -> toolkit class; action_hook.py registers `jitprompt_action`.
TOOLKITS = {"jitprompt": KnowledgeToolsJitprompt}


def _build_tools(variant, db, knowledge_base, read_log_allowlist=None):
    if variant.name not in TOOLKITS:
        return _upstream_build_tools(variant, db, knowledge_base, read_log_allowlist=read_log_allowlist)
    if not _DESCRIPTIONS_INSTALLED:
        raise RuntimeError(f"jitprompt arm needs {SNAPSHOT_FOR_TOOLS} (run jitprompt_snapshot.py first)")
    tools = TOOLKITS[variant.name](db, task_id=getattr(_current_task, "id", None))
    tools.set_read_log_allowlist(read_log_allowlist)
    return tools


def _get_environment(*args, task=None, **kwargs):
    _current_task.id = task.id if task else None
    return _upstream_get_environment(*args, task=task, **kwargs)


bk_env.build_tools = _build_tools
registry._domains["banking_knowledge"] = _get_environment
