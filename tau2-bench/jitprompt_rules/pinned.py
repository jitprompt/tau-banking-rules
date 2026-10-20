"""`jitprompt_pinned`: the jitprompt arm plus a few always-on "core procedure" docs.

Prototype of pinned core docs (stall correction), design frozen in
PROGRESS.md before any run. Models a jitprompt namespace that returns admin-pinned docs as
MCP server `instructions`, which clients place in the system prompt. Everything else is
identical to the jitprompt arm: same prompt, same three MCP tools, same namespace.
"""

from pathlib import Path
from typing import Optional

from tau2.domains.banking_knowledge import retrieval
from tau2.domains.banking_knowledge.data_model import KnowledgeBase

from jitprompt_rules.variants import PROMPT, TOOLKITS, KnowledgeToolsJitprompt

PINNED_DOCS = [
    "doc_bank_accounts_bank_accounts_(general)_009",  # Retrieving Customer Account Information
    "doc_bank_accounts_bank_accounts_(general)_042",  # Human Agent Transfer Reason Codes
]


def pinned_prompt(template_path: Path, knowledge_base: KnowledgeBase, task: Optional[object] = None) -> str:
    base = retrieval.standard_prompt(template_path, knowledge_base, task)
    docs = {d.id: d for d in knowledge_base.get_all_documents()}
    missing = [i for i in PINNED_DOCS if i not in docs]
    if missing:
        raise RuntimeError(f"pinned docs not in KB: {missing}")
    block = "\n\n---\n\n".join(f"## {docs[i].title}\n\n{docs[i].content}" for i in PINNED_DOCS)
    return (f"{base}\n\n# Core procedures (always apply)\n\n"
            f"These procedures apply to every conversation. For anything else, use the jitprompt tools.\n\n{block}")


TOOLKITS["jitprompt_pinned"] = KnowledgeToolsJitprompt
retrieval.RETRIEVAL_VARIANTS["jitprompt_pinned"] = retrieval.RetrievalVariant(
    name="jitprompt_pinned", prompt_template=PROMPT, build_prompt=pinned_prompt,
)
