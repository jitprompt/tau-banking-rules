# Claude Code brief: τ-Banking Rules, a planted-rule adherence benchmark for jitprompt

## Goal
Test the hypothesis the τ-Banking Lite run (`../t-bank/REPORT.md`) could not test:

> **"Tokens are cheap, attention isn't":** as an instruction corpus grows, agents with the whole corpus in the prompt follow specific, conditional rules less reliably than agents that retrieve just the relevant rules.

t-bank measured *task success on catalog lookups* with a strong model and found no degradation. This run measures **adherence to planted, conditional business rules** with a **cheaper agent model**, which is where the hypothesis is most likely to hold. Either outcome is publishable.

## Pre-registered primary analysis (do not change after seeing data)
- **Primary metric.** Rule adherence on *triggered* tasks: did the agent take the rule's required action, or avoid its forbidden one?
- **Primary comparison.** jitprompt vs full_prompt at tier XL, paired per (task, trial), exact McNemar test.
- **Everything else is secondary**: other tiers and arms, the control-task false-trigger rate, task pass, pass^2, breakdowns by rule type and by position.

## Reuse
Copy the harness from `../t-bank/tau2-bench/jitprompt_bench/`: tiers, variants, llm_patch (caching), cost ledger, jitprompt toolkit and logging, analyze. Upstream tau2 files stay untouched. New code goes in `tau2-bench/jitprompt_rules/` (or a fresh clone on branch `jitprompt-rules`). Read `../t-bank/PLAN.md`, the "Facts already established" section, before researching anything.

## Design

### 1. Planted rules (the treatment)
Write **24 rules** following `RULES_SPEC.md`: 4 of each of 6 types.
- **Every rule must be checkable deterministically from the action trace** (tool name, arguments, order). No LLM judge.
- **Each rule gets two tasks:**
  - a **triggered** task, where the condition holds and the rule changes the correct action;
  - a **control** task, where it nearly holds but doesn't (e.g. same scenario, different card or amount), so applying the rule is wrong.

  That gives 48 tasks.
- **Rule docs are written in the KB's own style** (title, `##` sections, bullets) and placed in one of two ways, half each:
  - **standalone:** a new doc, e.g. `doc_credit_cards_operational_update_901`;
  - **buried:** a copy of an existing product doc with the rule appended as a normal-looking section. The copy replaces the original in every tier.
- **Rule docs are listed in each task's `required_documents`.** Rules of type `exception` and `superseded` have 2 required docs.

### 2. Tasks
- Derive tasks from existing `banking_knowledge` tasks and DB users where possible: reuse their user scenarios and accounts, and change only what the rule needs. Where no existing user fits, add users and accounts to a **copy** of `db.json` used by this run only.
- Store tasks in `jitprompt_rules/tasks_rules.json`, in tau2's task schema. Set `evaluation_criteria.actions` to the full correct action sequence, so tau2's own grader gives task pass.
- A separate checker, `check_rules.py`, scores rule adherence from the simulation trajectory using each rule's `check` spec.

### 3. Corpus tiers
- **S:** union of required docs, including rule docs.
- **XL:** all 698 original docs, with buried-rule copies swapped in, plus standalone rule docs.
- **M** (optional, only if budget allows after the pilot): credit_cards + bank_accounts.

### 4. Position, full_prompt arm only
- With the corpus sorted by id, a rule's position in the prompt is incidental. Record each rule doc's token offset as a fraction of the prompt (0 = start, 1 = end) and report adherence by position tercile.
- Do **not** reorder per task. The cached prefix must stay byte-identical within a tier.

### 5. Arms (identical except for how knowledge is delivered)
- `full_prompt`: the tier KB as a cached system-prompt prefix.
- `rag_bm25`: upstream `bm25_grep`.
- `jitprompt`: production jitprompt **1.3.0 or later**, one namespace per tier with the rule docs ingested as-is. Record the server version.
- Reference conditions, run once on the S task set:
  - `required_docs`: the ceiling;
  - `no_rules`: required docs with the rule docs removed. This is the floor that shows the rules actually change behavior.

### 6. Models
- **Agent:** `anthropic/claude-haiku-5-5`, thinking disabled.
- **User simulator:** `anthropic/claude-sonnet-5-5` with `between_tools`. In t-bank, Haiku as the user simulator ignored its script.
- Optional second agent: Sonnet 5.5 on XL only, for contrast with t-bank.

### 7. Trials
k = 2 for everything. That's 96 paired observations per comparison, enough to detect a difference of about 15–20 points.

## Gates (stop and report at each)
1. **Authoring review.** Write `RULES_SPEC.md`-compliant `rules.yaml`, the rule docs and `tasks_rules.json`. Print a table of rule id, type, trigger, required/forbidden action and its control. **Stop for the user's review before spending anything.**
2. **Rule validity check** (≤$5):
   - Run Sonnet 5.5 as the agent with `required_docs` on all 48 tasks, k=1. Any rule Sonnet fails with gold docs in hand is ambiguous: fix it or drop it.
   - Run `no_rules` with Haiku on the triggered tasks. If Haiku complies by chance on more than 20%, the rule isn't distinctive: fix it.
   - Report how many rules survived. Continue only if ≥ 18 did.
3. **Ingest.** Ingest the new and changed docs into the jitprompt namespaces S and XL. Snapshot the TOC size and run a replay check: does `search_instructions` with the triggered task's plan return the rule doc?
4. **Pilot:** S + XL × 3 arms × 48 tasks × k=1, plus the reference conditions. Report adherence and spend.
5. **Full run:** k=2 at the same grid. M is optional.

**Hard budget cap: $90** of benchmark LLM calls, with a live guard at $85. Estimate cost from the pilot before Gate 5 and stop if the projection exceeds the cap.

## Outputs (`results/`)
- `runs.csv`: per (task, tier, arm, trial). Columns:
  - task_pass, rule_id, triggered (0/1), adhered (0/1), false_trigger (0/1)
  - rule position (full_prompt only), retrieval calls, rule doc retrieved (0/1)
  - tokens, cost
- `summary.csv`: per (tier, arm), with bootstrap CIs over tasks:
  - adherence (triggered tasks), false-trigger rate (controls), task pass, pass^2
- `by_type.csv`, `by_position.csv`.
- `paired.csv`: primary and secondary McNemar tests.
- `adherence_vs_corpus.png`: one line per arm, with the reference conditions as dashed lines.
- **Failure attribution for jitprompt misses:** was the rule doc never retrieved (retrieval miss), or retrieved but ignored (attention miss)? Do the same for BM25.
- `REPORT.md`: one page in t-bank's format, with an answer stated up front. Say plainly if the hypothesis isn't supported.

## Do not touch
Upstream evaluation code, the original tasks and `db.json`, and user simulator logic. Log any forced change in `DEVIATIONS.md`, and keep `PROGRESS.md` updated (gate status, decisions, spend, next action), as in t-bank.
