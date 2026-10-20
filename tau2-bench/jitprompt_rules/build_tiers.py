"""Build the corpus tiers for the planted-rules benchmark.

    uv run --no-sync python jitprompt_rules/build_tiers.py [--count-tokens]

Source corpus = the 698 upstream docs with the rule docs from rule_docs/ overlaid (buried
copies replace their originals; standalone docs are added). Run build_rules.py first.

Tiers (written to <out>/<tier>/, one JSON per doc, originals untouched):
- S          union of required_documents over the 48 tasks (rule-bearing versions)
- XL         all 698 docs (buried copies swapped in) + the standalone rule docs
- S_norules  S without the rule text: standalone rule docs removed, buried docs in their
             original upstream version (the `no_rules` reference reads this tier)

<out>/manifest.json records doc ids, token counts and, for the full_prompt arm, each rule
doc's position in the rendered full_kb system prompt as a fraction (0 = start, 1 = end):
for a buried doc the position of its appended rule section, for a standalone doc its start.
Positions use characters always and real Haiku tokens with --count-tokens (free endpoint).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
DOMAIN = REPO / "data/tau2/domains/banking_knowledge"
DEFAULT_OUT = REPO.parent / "data/tiers"
load_dotenv(REPO / ".env")

TASKS = json.loads((HERE / "tasks_rules.json").read_text())
_DROPPED = {r["id"] for r in __import__("yaml").safe_load((HERE / "rules.yaml").read_text()) if r.get("dropped")}
ALL_TASK_IDS = [t["id"] for t in TASKS]  # corpus tiers are built from all tasks (dropped rules stay as distractors)
TASK_IDS = [t for t in ALL_TASK_IDS if t.split("_")[1] not in _DROPPED]  # tasks that are run and analysed
TIERS = ["S", "XL", "S_norules"]
COUNT_MODEL = "claude-haiku-5-5"


def category(doc_id: str) -> str:
    return "_".join(doc_id.removeprefix("doc_").split("_")[:2])


def load_dir(path: Path) -> dict[str, dict]:
    docs = {}
    for p in sorted(path.glob("*.json")):
        doc = json.loads(p.read_text())
        assert p.stem == doc["id"], f"filename/id mismatch: {p}"
        docs[doc["id"]] = doc
    return docs


def load_rules() -> list[dict]:
    import yaml

    return yaml.safe_load((HERE / "rules.yaml").read_text())


def tier_docs() -> tuple[dict[str, dict[str, dict]], dict]:
    upstream = load_dir(DOMAIN / "documents")
    rule_docs = load_dir(HERE / "rule_docs")
    rules = load_rules()
    placement = {d["id"]: d for r in rules for d in r["docs"]}
    assert set(placement) == set(rule_docs), "rule_docs/ out of date: run build_rules.py"
    full = {**upstream, **rule_docs}
    required = sorted({d for t in TASKS for d in t["required_documents"]})
    missing = [d for d in required if d not in full]
    assert not missing, f"required docs not in corpus: {missing}"
    s = {d: full[d] for d in required}
    norules = {d: upstream[d] for d in required if placement.get(d, {}).get("placement") != "standalone"}
    tiers = {"S": s, "XL": dict(sorted(full.items())), "S_norules": norules}
    assert set(tiers["S"]) <= set(tiers["XL"])
    assert set(rule_docs) <= set(tiers["S"]), "every rule doc must be required by some task"
    for d, doc in norules.items():
        assert doc == upstream[d]
    return tiers, placement


def full_kb_prompt(tier_dir: Path) -> str:
    """The exact full_kb system-prompt policy tau2 renders for this tier, loaded the way
    tau2_entry loads it at run time (KnowledgeBase.load, then sorted by id)."""
    from tau2.domains.banking_knowledge.data_model import KnowledgeBase
    from tau2.domains.banking_knowledge.retrieval import build_policy, resolve_variant

    kb = KnowledgeBase.load(str(tier_dir))
    kb = KnowledgeBase(documents=dict(sorted(kb.documents.items())))
    return build_policy(resolve_variant("full_kb"), kb)


def count_tokens(text: str) -> int:
    import anthropic

    return anthropic.Anthropic().messages.count_tokens(
        model=COUNT_MODEL, messages=[{"role": "user", "content": text}]).input_tokens


def rule_positions(prompt: str, docs: dict, placement: dict, rules: list[dict], tokens: bool) -> dict:
    total_tok = count_tokens(prompt) if tokens else None
    out = {}
    for r in rules:
        for d in r["docs"]:
            if d["id"] not in docs:
                continue
            doc = docs[d["id"]]
            if d["placement"] == "buried":
                needle = f"## {d['section']}\n\n" + d["text"].strip()
            else:
                needle = f"## {doc['title']}\n\n{doc['content']}"
            at = prompt.find(needle)
            assert at >= 0, f"{d['id']}: rule text not found in rendered prompt"
            pos = {"rule_id": r["id"], "placement": d["placement"], "char_frac": round(at / len(prompt), 4)}
            if tokens:
                pos["token_offset"] = count_tokens(prompt[:at]) if at else 0
                pos["token_frac"] = round(pos["token_offset"] / total_tok, 4)
            out[d["id"]] = pos
    return {"prompt_chars": len(prompt), "prompt_tokens": total_tok, "rule_docs": out}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--count-tokens", action="store_true")
    args = p.parse_args()

    tiers, placement = tier_docs()
    rules = load_rules()
    manifest = {"tasks": TASK_IDS, "dropped_rules": sorted(_DROPPED), "count_model": COUNT_MODEL if args.count_tokens else None, "tiers": {}}
    for tier, docs in tiers.items():
        d = args.out / tier
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for doc_id, doc in docs.items():
            (d / f"{doc_id}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        cats: dict[str, int] = {}
        for i in docs:
            cats[category(i)] = cats.get(category(i), 0) + 1
        entry = {"n_docs": len(docs), "categories": dict(sorted(cats.items())), "doc_ids": sorted(docs)}
        if tier != "S_norules":  # positions matter for the full_prompt arm only
            prompt = full_kb_prompt(d)
            entry["full_prompt"] = rule_positions(prompt, docs, placement, rules, args.count_tokens)
        manifest["tiers"][tier] = entry
        fp = entry.get("full_prompt", {})
        print(f"{tier:>9}: {len(docs):>3} docs"
              + (f", full_kb prompt {fp['prompt_chars']} chars" if fp else "")
              + (f" / {fp['prompt_tokens']} tokens" if fp.get("prompt_tokens") else ""))
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
