"""Arms for jitprompt >= 1.3.1 server-side pinned documents (replaces the pinned.py prototype).

- `jitprompt_sysprompt`: models a client that puts MCP `instructions` in the system prompt (as
  Claude Code does). The prompt is the jitprompt arm's prompt plus the server's `instructions`,
  verbatim, fetched at initialize under client name `tau2-jitprompt-bench-sysprompt`. The server
  treats this client name as one that reads `instructions`, so it adds no in-band copy.
- `jitprompt_inband`: the stock client (`tau2-jitprompt-bench`, not allowlisted), which ignores
  `instructions`. The server prepends the pinned block to the first get_toc / search_instructions
  response of each MCP session.

Both run one MCP session per conversation (run.py sets JB_JP_SESSION=conversation and
JB_JP_CLIENT_NAME per arm); see variants.JitpromptMixin._client.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tau2.domains.banking_knowledge import retrieval
from tau2.domains.banking_knowledge.data_model import KnowledgeBase

from jitprompt_rules.jitprompt_client import PINS_HEADER, new_client
from jitprompt_rules.variants import PROMPT, TOOLKITS, KnowledgeToolsJitprompt, _tier

SYSPROMPT_CLIENT = "tau2-jitprompt-bench-sysprompt"
INBAND_CLIENT = "tau2-jitprompt-bench"
REQUIRED_VERSION = "1.3.1"


@lru_cache(maxsize=4)
def server_instructions(tier: str, client_name: str) -> tuple[str, dict]:
    """(instructions, serverInfo) from one initialize. Identical for every session of a namespace."""
    client = new_client(tier, client_name).connect()
    info = client.server_info.get("serverInfo") or {}
    if info.get("version") != REQUIRED_VERSION:
        raise RuntimeError(f"jitprompt server is {info.get('version')}, this arm needs {REQUIRED_VERSION}")
    if not client.instructions or not client.instructions.startswith(PINS_HEADER):
        raise RuntimeError("namespace returned no pinned-docs instructions; check GET /pins")
    return client.instructions, info


def sysprompt_prompt(template_path: Path, knowledge_base: KnowledgeBase, task: Optional[object] = None) -> str:
    base = retrieval.standard_prompt(template_path, knowledge_base, task)
    instructions, _ = server_instructions(_tier(), os.environ.get("JB_JP_CLIENT_NAME", SYSPROMPT_CLIENT))
    return f"{base}\n\n{instructions}"


TOOLKITS["jitprompt_sysprompt"] = KnowledgeToolsJitprompt
TOOLKITS["jitprompt_inband"] = KnowledgeToolsJitprompt
retrieval.RETRIEVAL_VARIANTS["jitprompt_sysprompt"] = retrieval.RetrievalVariant(
    name="jitprompt_sysprompt", prompt_template=PROMPT, build_prompt=sysprompt_prompt,
)
retrieval.RETRIEVAL_VARIANTS["jitprompt_inband"] = retrieval.RetrievalVariant(
    name="jitprompt_inband", prompt_template=PROMPT, build_prompt=retrieval.standard_prompt,
)
