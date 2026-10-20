# Plan: τ-Banking Rules, planted-rule adherence benchmark

> First execution step: copy this file to `t-rules/PLAN.md` and create `PROGRESS.md` and `DEVIATIONS.md` next to it.
> Resume order for later sessions: BRIEF.md → PLAN.md → PROGRESS.md.

## Context
- **What t-bank found.** Task success on catalog lookups did not degrade with corpus size (Sonnet 5.5, 36K→296K tokens).
- **What this run tests.** "Tokens are cheap, attention isn't", where the hypothesis is most likely to hold:
  - Adherence to 24 planted, conditional business rules.
  - A cheaper agent: Haiku 5.5 with thinking disabled.
  - Primary comparison: jitprompt vs full_prompt at XL, paired exact McNemar. It is pre-registered and stays fixed.
- **User decisions (2026-10-14).**
  - Fresh tau2 clone in t-rules.
  - jitprompt namespaces built by duplicating t-bank XL.
  - Adherence scored intent-to-treat: a run that never reaches the decision point counts as non-adherent. Every rule's check includes a positive required action, so doing nothing never scores as adherence. Conditional adherence is reported as secondary.

## Facts from exploration that shape the design
- **Clock.** `get_current_time` is fixed at **2025-11-14 03:40 EST**, so every rule date must sit around 2025, not 2026.
  - Example: R04's old doc dated 2025-03-01; the new doc "effective 2025-10-01".
- **Two seed examples conflict with the existing KB.**
  - `credit_card_account_logistics_002` and `_003` already require account age ≥ 60 days and no pending replacement card before closure. So R02's seed rule (no closure with a pending replacement) is already in the KB, and R03's 45-day trigger is blocked by the KB anyway.
  - Fix: author a different R02 trigger, and move R03's trigger into the 60–180 day range (e.g. 90 days triggered vs 400 control).
  - General authoring rule: for every rule, grep the KB to check that no existing doc already implies it or contradicts it. Contradicting is allowed only for `exception` and `superseded`.
- **Most write tools are discoverable.** The agent calls `call_discoverable_agent_tool(agent_tool_name, arguments=<JSON string>)`, and ints are parsed as floats. `check_rules.py` must therefore unwrap the inner tool name and its JSON arguments, and normalise numbers.
- **The write tools don't enforce eligibility.** `close_credit_card_account_7834` and `apply_statement_credit_8472` do no checks, so the KB is the only gate. That makes rules over these tools cleanly testable.
- **`promotional_apr` is never mentioned in the KB.** Rules that use it are introduced only by the rule docs, which is good for distinctiveness.
- **How grading works.**
  - Grading is a DB hash after golden-action replay.
  - Read tools are logged only if they appear in the golden actions. A read that is in the golden actions but called a different number of times changes the hash.
  - Task pass will therefore be strict and noisy. It is secondary.
- **How tasks and DB are loaded.**
  - The runtime loads tasks from `bk_env.KNOWLEDGE_TASK_SET_PATH` (a glob of `task_*.json` files) and the DB from `bk_env.KNOWLEDGE_DB_PATH`. Both are module globals read at call time, so `tau2_entry` can repoint them without touching upstream.
  - Per-task DB state goes in `initial_state.initialization_data.agent_data`, which is merged into the DB. This is enough for account age, pending orders and the like, so a `db.json` copy is needed only for brand-new users.
- **How golden prompts are built.** `golden_prompt` (`retrieval.py:356`) reads `task.required_documents` from the loaded KB. `get_info_policy_override` calls builders with `task=None`, so they must tolerate that.
- **Ledger.** The t-bank ledger is cumulative, and its caps are $115 / $113. This run gets its own ledger with caps of $90 (pre-check) and $85 (hard stop).

## Layout
```
t-rules/
  BRIEF.md RULES_SPEC.md PLAN.md PROGRESS.md DEVIATIONS.md REPORT.md
  tau2-bench/                       # fresh clone @ dd8757d, branch jitprompt-rules; upstream untouched
    jitprompt_rules/                # copied from t-bank jitprompt_bench, then adapted
      rules.yaml                    # 24 rules (RULES_SPEC schema)
      rule_docs/                    # new standalone docs + buried copies (JSON {id,title,content})
      tasks_rules.json              # 48 tasks, tau2 schema
      db_rules.json                 # db.json copy + any added users (only if needed)
      build_rule_docs.py            # rules.yaml → rule_docs/*.json (+ stripped originals for no_rules)
      build_tasks.py                # emits tasks_rules.json → tasks/task_R##_{t,c}.json for the loader
      build_tiers.py                # S / XL (/M) with rule-doc swaps, manifest, token counts, rule positions
      check_rules.py                # deterministic adherence scorer
      tau2_entry.py variants.py run.py cost.py jitprompt_client.py jitprompt_snapshot.py
      ingest_jitprompt.py prune_namespace.py replay_retrieval.py analyze.py check_batch.py prompts/
  data/tiers/{S,XL,S_norules}/
  results/
```

## Steps

### 0. Setup (no spend)
- Clone tau2-bench at `dd8757d` into `t-rules/tau2-bench` and create branch `jitprompt-rules`.
- Run `uv sync --extra knowledge`, then add the same extras as t-bank: `anthropic`, `mcp`, `websockets`, `matplotlib`. Copy `.env`.
- Copy `jitprompt_bench/` to `jitprompt_rules/`. Make these things configurable instead of hardcoded:
  - **Task source.** In `tau2_entry`, patch `bk_env.KNOWLEDGE_TASK_SET_PATH` to `jitprompt_rules/tasks/`, and `KNOWLEDGE_DB_PATH` to `db_rules.json` if that file exists.
    - Replace the `TASK_IDS` import used by run, check_batch, replay and analyze with a list read from `tasks_rules.json`.
  - **Tiers.** Set `TIERS = S, XL` (plus M as an option) and `TIERS_DIR = t-rules/data/tiers`. Pass the doc source dir as an argument.
  - **Reference arms.** Route `required_docs` and `no_rules` to tier dirs instead of upstream `documents/`:
    - `required_docs` reads tier XL, which holds every doc in its rule-bearing version;
    - `no_rules` reads `S_norules`, where standalone rule docs are removed and buried docs revert to their original text.
    - Register a `no_rules` variant in `variants.py` that reuses `golden_prompt` with the standalone rule ids filtered out of `required_documents`, and handles `task=None`.
  - **Cost and models.**
    - Keep Haiku 5.5 thinking `disabled` for the agent; the user simulator is Sonnet 5.5 with `between_tools`.
    - Set `run.py` `BUDGET_CAP=90`, `cost.py` `HARD_STOP_USD=85`, and point the ledger at `t-rules/results/ledger.jsonl`.
  - **Logging.**
    - Add the trial and raw output to `retrieval_calls.jsonl`.
    - Add BM25 call logging, which was planned in t-bank but never built.
    - Load tool descriptions from the new namespace's snapshot.
- Smoke test: one original task (task_002) with `required_docs` through the new entry, to confirm the ledger works and the grading is unchanged (cost about $0.05).

### Gate 1: Authoring (no spend). STOP for review
- **`rules.yaml`.** 24 rules, 4 per type, following `RULES_SPEC.md`.
  - Spread them over credit_cards and bank_accounts.
  - 32 docs in total (8 rules have 2 docs, 16 have 1), half standalone (`doc_<cat>_operational_update_9NN`) and half buried (appended `##` section in an existing product doc, same id).
- **Author from the existing scenarios.** Start from tasks 043/045 (closure and retention), 050/051 (credit limit increase), 072–074 (checking credits), 093–097 (savings credits), 036/037 (replacement cards) and 060–069 (open and close bank accounts).
  - Prefer short flows, because Haiku's task-pass ceiling was about 30% in t-bank and noise near the decision point dilutes adherence.
  - Put the trigger conditions in `agent_data` (dates, balances, orders) or in the user's words.
- **Per rule:**
  - Check the KB for conflicts (grep the trigger terms).
  - The check spec always contains a positive `required` action.
  - A `check_control` defines the false-trigger signature, i.e. the rule's distinctive action appearing on the control task.
- **`build_rule_docs.py` and `build_tasks.py`.**
  - Golden `evaluation_criteria.actions` must be a full sequence, including the unlock and call pairs and the read tools.
  - Validate each golden sequence by replaying it in a fresh environment, so that it actually reaches the intended DB state.
- **`check_rules.py`** runs on the golden trajectories as a unit test:
  - the triggered gold must give `adhered=1`;
  - the control gold must give `false_trigger=0`;
  - and the triggered gold must fail when scored as if it were the control, and vice versa.
- **Deliverable for the review:** a table of rule id, type, trigger, required/forbidden action, control difference and placement, plus the KB-conflict notes.

### Gate 2: Rule validity (about $7, slightly over the ≤$5 the brief targets; Sonnet runs at about $0.12 each)
- **Sonnet 5.5 agent, `required_docs`, 48 tasks, k=1.** A rule fails if Sonnet misses it on the triggered task, or false-triggers on its control. Fix or drop failing rules.
- **Haiku agent, `no_rules`, 24 triggered tasks, k=1.** A rule fails if Haiku complies by chance more than 20% of the time. With k=1 that means any compliance, so re-run those rules once to confirm before fixing.
- Report how many rules survive. Continue only if at least 18 do.
- Rules that are dropped are excluded from every later analysis, and this is logged in PROGRESS.

### Gate 3: Tiers + jitprompt ingest (cents)
- **`build_tiers.py`.**
  - S is the union of required docs across all 48 tasks, with the rule versions of every doc.
  - XL is 698 docs with the buried copies swapped in, plus the standalone docs.
  - `S_norules` is described in Step 0.
  - Assert that the required docs ⊂ S ⊂ XL.
  - Get token counts from `count_tokens` (free).
  - Record **rule position**: the token offset of each rule section within the rendered full_kb system prompt, as a fraction of its length. Compute it per tier with `count_tokens` on the prefixes. The KB is sorted by id; it is never reordered per task.
- **jitprompt namespaces.** The user duplicates t-bank XL into `RULES_XL` and `RULES_S` and adds `JITPROMPT_KEY_RULES_XL` and `_RULES_S`. Then:
  - delete the buried originals in both namespaces;
  - ingest the 16 buried copies and the 16 standalone docs (about 64 ingestions in all);
  - prune RULES_S to the S manifest;
  - verify that each namespace's doc set equals its manifest.
- Use the `catalog` retrieval profile for continuity with t-bank; the user sets it.
- **Snapshot.** Record the server version (assert ≥ 1.3.0), the TOC size, and the section→doc maps.
- **Replay check** (`replay_retrieval.py --source plans`). For each triggered task, does `search_instructions(plan)` return the rule doc(s)? Report the rate per tier. It also records the newer `created_at` caveat for TOC order.

### Gate 4: Pilot (estimated at about $31)
- The grid is {S, XL} × {full_prompt, rag_bm25, jitprompt} × 48 tasks, plus `required_docs` and `no_rules` on the 48 tasks, all at k=1.
- Pre-warm the full_prompt cache per tier.
- Order: references, then S, then XL, with full_prompt XL last.
- Run `check_batch.py` after each cell.
- Report adherence, false triggers, task pass and spend per cell, and project the full-run cost.

### Gate 5: Full run
- Run trial 2 on the same grid, reusing the pilot as trial 1 if the code is unchanged (`--auto-resume`, same save paths). This gives k=2, so 2 runs per task and up to 96 paired triggered observations.
- Stop if the projected spend exceeds $90. M is optional and only if budget remains.

### Analysis (`analyze.py`, rewritten around `check_rules.py`)
- **`runs.csv`.** One row per (task, tier, arm, trial) with the BRIEF.md columns.
  - Also `reached_decision_point`, which is secondary.
  - Also `rule_doc_retrieved`, taken from the jitprompt or BM25 logs; for full_prompt and the references the doc is always present.
- **`summary.csv`.** Adherence, false-trigger rate, task pass and pass^2 per (tier, arm), with bootstrap CIs over rules (seed 0).
- **`paired.csv`.**
  - Primary: jitprompt vs full_prompt at XL, as an exact McNemar test on (task, trial) pairs.
  - Secondary: the other pairs and tiers.
- **`by_type.csv` and `by_position.csv`.** Position terciles, for full_prompt only.
- **Failure attribution** for missed jitprompt and BM25 runs: `retrieval_miss` if the rule doc was never surfaced, `attention_miss` if it was surfaced but not followed, `task_hard` if `required_docs` also fails.
- **Chart.** `adherence_vs_corpus.png`, with dashed lines for the references.
- **`REPORT.md`.** One page in t-bank's format, with the answer up front. It says plainly if the hypothesis isn't supported.

## Cost estimate (to verify in the pilot)
| Item | Per run | Runs | Total |
|---|---|---|---|
| Retrieval arms and references, Haiku agent + Sonnet user simulator | ~$0.05–0.06 | 240 per trial | ~$13 |
| full_prompt S (~40K prompt) | ~$0.04 | 48 | ~$2 |
| full_prompt XL (~300K, Haiku long-context cache read $0.05/M × ~15 calls) | ~$0.28 | 48 | ~$13 |
| **Per trial** | | | **~$31** |

- Gate 2 adds about $7 and the smoke test about $0.1. With k=2, the total is about **$69**, under the $85 hard stop.
- The user simulator (Sonnet) is likely the largest cost in the retrieval arms. Measure it in the smoke test.

## Verification
- **Golden sequences.** Each task's golden actions replay without errors and its DB hash is reproducible. `check_rules.py` unit tests pass on gold, including the cross-checks.
- **Tiers.** The required-doc and subset assertions pass. Buried copies differ from the originals only by the appended section (diff check). `S_norules` contains no rule text: grep for each rule's key sentence.
- **jitprompt.** Namespace doc sets match the manifests exactly, every doc is ready, the version is ≥ 1.3.0, and a test search's ids appear in the call log.
- **Upstream untouched.** `git diff dd8757d --stat` shows only `jitprompt_rules/`.
- **Analysis.** pass^k matches tau2's `pass_hat_k`. The McNemar test is recomputed by hand for the primary cell.
