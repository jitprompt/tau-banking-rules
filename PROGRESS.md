# PROGRESS — τ-Banking Rules × jitprompt

Resume order: BRIEF.md → PLAN.md → this file. Update after every gate.

## Spend ledger (benchmark LLM calls; cap $90, live guard $85; ledger results/ledger.jsonl)
| Date | Step | Spend | Cumulative |
|---|---|---|---|
| 2026-10-14 | planning | $0.00 | $0.00 |
| 2026-10-15 | Gate 3 replay plans (48 Haiku calls) | $0.005 | $0.005 |
| 2026-10-15 | Gate 2 pass 1 (Sonnet gold 48 + Haiku no_rules 24, incl. $0.04 smoke) | $3.31 | $3.31 |
| 2026-10-15 | Gate 2 re-runs after fixes (Sonnet 12 + Haiku 5) | $0.87 | $4.14 |
| 2026-10-15 | Pilot (k=1, 8 cells x 46 tasks + 2 smoke runs) | $8.85 | $12.99 |
| 2026-10-15 | Trial 2 (same grid, k=2) | $10.50 | $23.49 |
| 2026-10-15 | Action-hook test (jitprompt_action @XL, k=2, incl. 7 re-runs) | $1.29 | $24.78 |
| 2026-10-15 | Pinned-docs test (jitprompt_pinned @XL, k=2) | $0.89 | $25.68 |
| 2026-10-15 | jitprompt 1.3.1 arms (sysprompt + inband @XL, k=2) | $1.68 | $27.36 |

## Gates
- [x] 0. Setup: fresh clone, harness copied/adapted (paid smoke test deferred to Gate 2: no spend before review)
- [~] 1. Authoring review (rules.yaml, rule docs, tasks_rules.json) — DONE, awaiting user review (RULES_TABLE.md)
- [x] 2. Rule validity: 23/24 pass; R05 dropped (user, 2026-10-15)
- [x] 3. Tiers + jitprompt ingest + replay check (results/replay/replay_plans.csv)
- [x] 4. Pilot k=1 (results/*.csv, adherence_vs_corpus.png)
- [x] 5. Full run k=2 (user chose k=2 as pre-registered). REPORT.md written.

## Decisions
- 2026-10-14 (user): fresh tau2 clone in t-rules; namespaces by duplicating t-bank XL; adherence is intent-to-treat (no decision point reached = non-adherent), conditional adherence secondary.
- Seed examples R02/R03 in RULES_SPEC conflict with existing KB (logistics_002/003 already require ≥60 days age and no pending replacement for closure) — will be re-authored.
- Clock is fixed at 2025-11-14; all rule dates are set in 2025.

## Log
- 2026-10-14: Plan approved.
- 2026-10-14: Step 0 done. tau2-bench cloned @ dd8757d into t-rules/tau2-bench, branch jitprompt-rules; venv + anthropic/mcp/websockets/matplotlib/pyyaml; .env copied with t-bank JITPROMPT_KEY_* lines REMOVED (this run reads JITPROMPT_KEY_RULES_<tier> only, so it can never touch t-bank namespaces). Harness copied to jitprompt_rules/ (module renamed). tau2_entry loads tasks from jitprompt_rules/tasks/ (48 tasks verified via the registry). run.py: arms required_docs→tier S, no_rules→tier S_norules (golden_retrieval on a KB with rule text removed; no new variant needed), save names jr_*, caps $90/$85, user sim default Sonnet. variants.py: jitprompt arm refuses to run until the RULES namespaces are snapshotted.
- 2026-10-14: Gate 1 authored. jitprompt_rules/rules.yaml → build_rules.py → rule_docs/ (36 docs: 18 standalone, 18 buried), tasks/ + tasks_rules.json (48 tasks). check_rules.py scores adherence/false triggers from the tool-call trajectory. `build_rules.py --validate`: every golden sequence replays with no tool error, and all 24 rules pass the 4 cross-checks (triggered gold adheres; control gold correct; each gold fails the other kind's check).
  - KB-conflict scan done (regex over all 698 docs). Fixed: R01 fee set to the KB's $32.50 late fee. Accepted: Silver savings has a $5,000/day mobile cap (different channel from R02's agent-assisted $2,500); replacements_001 already says to review transactions *after* a stolen-card order (R21 says before, with the tool).
  - No db_rules.json needed: all per-task state (balances, dates, transactions, prior orders/CLIs, payment history, frozen cards, 3 new accounts) is injected via initial_state agent_data.
  - NEXT: user reviews RULES_TABLE.md. Then (no spend) build_tiers S / XL / S_norules, then Gate 2 (~$7).
- 2026-10-14: Tiers built (build_tiers.py, rewritten): S 49 docs / 29,855 tok full_kb prompt; XL 716 docs / 303,507 tok; S_norules 31 docs. manifest.json has each rule doc's position in the full_kb prompt (char + token fraction).
  - FINDING: XL position terciles are 13 / 0 / 23 (no rule doc in the middle third: id order puts bank_accounts docs at 0.01–0.10 and credit_cards at ~0.67–0.85). S: 6 / 11 / 19. The by-position analysis will lack a middle bin at XL; positions are incidental by design (no per-task reordering).
- 2026-10-14: User duplicated t-bank XL → RULES_XL, RULES_S; keys JITPROMPT_KEY_RULES_{XL,S}. sync_namespace.py (new): replaces 18 buried originals, uploads 18 standalone docs, prunes S, re-uploads structurer failures, tracks content hashes in results/jitprompt/sync_<tier>.json. Result: RULES_XL = exactly 716 tier docs, RULES_S = exactly 49, all ready. Server instructions 1.3.0. Ingest failed transiently on gold_rewards_card_001 (3x) and bank_accounts_operational_update_903 (1x); succeeded on retry. Snapshots: S 208 sections, get_toc 5,339 tok; XL 2,967 sections, get_toc 93 tok (condensed). Retrieval profile `catalog` set by user (not verifiable via MCP).
  - NEXT: user confirms Gate 1 review → replay check (replay_retrieval.py --source plans --tiers S XL, ~$0.01) and Gate 2 (~$7).
- 2026-10-15: Gate 3 replay check (one Haiku-written plan per task, from the user script; results/replay/plans.json). Rule doc returned (any rule doc / all rule docs of the task), triggered tasks:
  - jitprompt search_instructions: S 1.00 / 0.95, XL 1.00 / 0.91. get_toc(query): S 1.00 / 1.00, XL 1.00 / 0.93.
  - BM25 top-10: S 1.00 / 0.89, XL 0.92 / 0.76 (two-doc rules 0.62). BM25 misses at XL: R05_t, R05_c, R06_c, R16_t, R19_c.
  - Caveat: these plans are written from the full user script, so they name the trigger facts (direct deposit, Platinum, etc.). Real agent queries come before the facts are known and may retrieve less; the logged-query replay after the pilot will show that. If retrieval stays near-perfect, the jitprompt-vs-full_prompt comparison mostly measures attention, not retrieval.
  - NEXT: Gate 2 (~$7) on user go-ahead.
- 2026-10-15: Gate 2 pass 1 (jr_g2sonnet_required_docs, jr_g2haiku_no_rules): 19/24 ok. Failures were task-design bugs, fixed:
  - R05, R23: required docs lacked bank_accounts_(general)_009 (the account-lookup tool doc) -> agent could not find account ids. Added.
  - R08 (and all transfer flows): user simulator said ###TRANSFER### before the agent called the tool. Scripts now say: wait until the agent confirms the transfer.
  - R11: account opened 09/15 was outside silver_009's offer window (2025-10-15..12-31). Now opened 10/20/2025; expirations 10/20/2026 (standard) / 01/20/2027 (Plus).
  - R03 control: tier mapping (Gold = premium) only appears in credit_card_replacements_002; added to all tier-dependent tasks (R03, R09, R13, R14, R16, R24).
  - R07 control: checker required an exact address string; now card + reason. User states the street address plainly.
  - R09: Haiku without rules closed the card, which WAS the exception's action (not distinctive). Redesigned: base = 'no retention offers under 180 days' (standalone 904), exception = 'Gold annual-fee closures always get the 12-month waiver' (buried gold_005). Triggered: Gold, 136 days -> waiver. Control: personal Silver, 136 days -> close, no offer.
  - Rule docs changed only for R09 (gold_005); namespaces re-synced and re-snapshotted. Character home cities removed from scripts (conflicted with DB addresses).
- 2026-10-15: Gate 2 re-runs (jr_g2b_*): R03 c, R05, R07 c, R08, R09, R11, R23 now pass with Sonnet gold docs. R05 still WEAK: Haiku no_rules transferred on 2/2 runs. Cause: Haiku fails the discoverable-tool mechanics (doesn't unlock close_bank_account_7392 / can't find account) and falls back to a transfer, which is R05's required action. R06-R08 (also transfer rules) were 0/1 under no_rules.
  - Measured cost per run (ledger): Haiku agent + Sonnet user ~$0.009; Sonnet agent + Sonnet user ~$0.065. Much below the plan's $0.05 estimate for Haiku runs.
  - Observation for the report: Haiku sometimes mishandles discoverable tools (direct calls without unlock; claims a tool is unavailable). This lowers task pass for every arm equally.
- 2026-10-15: R05 dropped (user). 23 rules / 46 tasks active; R05's doc stays in the corpus as a distractor.
- 2026-10-15: PILOT DONE (batch `pilot`, Haiku 5.5 agent thinking off, Sonnet 5.5 user between_tools, k=1). All 8 cells 46/46 clean.
  - Adherence on triggered tasks (23 rules), 95% CI resampling rules:
    S: full_prompt 0.91 [0.78, 1.0], rag_bm25 0.83 [0.65, 0.96], jitprompt 0.87 [0.74, 1.0]
    XL: full_prompt 0.48 [0.26, 0.70], rag_bm25 0.65 [0.43, 0.83], jitprompt 0.74 [0.57, 0.91]
    References: required_docs 1.00, no_rules 0.00.
  - Primary (pilot = trial 1 only): jitprompt@XL vs full_prompt@XL 6-0 discordant, exact McNemar p = 0.031. full_prompt S→XL 10-0, p = 0.002.
  - False-trigger rate on controls: full_prompt 0.13 → 0.17, jitprompt 0.04 → 0.13, rag_bm25 0.00 → 0.13; required_docs 0.04.
  - Rule doc retrieved (triggered): jitprompt 1.00 / 0.96, rag_bm25 0.96 / 0.96. Misses at XL are mostly attention misses (jitprompt 5 of 6, BM25 7 of 8).
  - full_prompt@XL by position tercile: first third 0.13 (n=8, the bank_accounts rules), middle n/a, last third 0.67 (n=15). Position is confounded with category (BA vs CC).
  - Task pass is low everywhere (0.04–0.17); Haiku's verification logging and discoverable-tool handling dominate it. Secondary.
  - Cost per run (ledger): full_prompt XL $0.131; all other cells ~$0.009.
  - Projection: one more trial of the same grid ≈ $8.9 → total ≈ $22 at k=2 (cap $90).
  - NOTE: the brief's "96 paired observations" assumed 48 triggered tasks; triggered tasks are 23 (24 rules, 1 dropped), so k=2 gives 46 pairs for the primary test.
  - NEXT: user decides Gate 5 scope (k=2 as pre-registered, or more trials / optional M tier / Sonnet XL contrast).
- 2026-10-15: User chose k=2. Trial 2 run on the pilot save paths (--trials 2 --auto-resume; tau2 derives trial seeds from seed 300, so trial 1 was recognised as done). run.py pre-warm fixed to run the first task's next pending trial (the old 1-trial warm-up would have been a no-op).
- 2026-10-15: FULL RUN DONE. All 8 cells 92/92 runs (46 tasks x 2 trials), none abnormal. Total spend $23.49.
  - PRIMARY: jitprompt@XL 0.674 vs full_prompt@XL 0.500, 8-0 discordant, exact McNemar p = 0.008 (n = 46 pairs). Hypothesis supported for Haiku 5.5.
  - full_prompt S 0.80 → XL 0.50 (16-2, p = 0.001); jitprompt 0.85 → 0.67 (p = 0.039); BM25 0.80 → 0.67 (p = 0.146). jitprompt = BM25 at XL (4-4).
  - XL misses in retrieval arms are mostly attention misses (jitprompt 13/15, BM25 12/15).
  - full_prompt XL: bank_accounts rules (prompt start) 0.19 vs credit_cards (last third) 0.67; retrieval arms also drop on BA rules at XL, so position and category/distractor load are confounded.
  - Exception rules: full_prompt 0/8 at XL.
  - Outputs: results/{runs,summary,paired,by_type,by_position,attribution}.csv, adherence_vs_corpus.png, REPORT.md.
  - Not run (optional per brief): M tier, Sonnet 5.5 agent on XL. Remaining budget ~$66.
- 2026-10-15: USER: test improvement #1 (action-indexed retrieval). PRE-REGISTERED before any run (design frozen; no iteration on these rules):
  - Arm `jitprompt_action` @XL, k=2, 46 tasks, batch `action`: identical to `jitprompt` (same prompt, same MCP tools, namespace RULES_XL) plus a pre-call hook on every state-mutating discoverable tool call.
  - Index (local prototype of the ingest step): all 716 XL docs split at `## ` headings. Match terms per call: the tool name (weight 2); string argument values that look like enums (snake_case or UPPERCASE, weight 1); argument keys that are not generic ids/amounts (weight 1). A section is a candidate if score >= 2. Top 3 by score within ~2.5K tokens; sections the agent has already seen in this conversation (jitprompt outputs or earlier hook output) are skipped.
  - If unseen governing sections exist, the call is NOT executed; the agent gets them with "call it again if the call complies". The next call executes (sections now seen). No DB effect while blocked.
  - Known limitation: literal matching only (no LLM mapping of prose to actions), so rules that don't name the tool or an enum value are invisible to it (e.g. R09's 180-day doc, R11's Plus doc).
  - PRIMARY for this test: jitprompt_action@XL vs jitprompt@XL (pilot batch), exact McNemar on 46 (task, trial) pairs of triggered runs; success = p < 0.05 in favour of the hook. Secondary: vs rag_bm25@XL and full_prompt@XL; false-trigger rate on controls; reached rate. Caveat: comparison arms ran earlier, not concurrently.
- 2026-10-15: Action-hook test (pre-registered above). Offline replay of the frozen hook over the earlier jitprompt XL runs predicted ~no effect: 13/15 misses would never trigger it (no write call made, or governing sections already seen), 0/15 would newly show the rule doc; R24 not matched (its rule names `loyalty_benefit` but not the tool, score 1 < 2).
  - Live run: 7/92 runs failed grading (strict replay mismatch, harness bug: the hook's seen-filter isn't reconstructed in replay). Fixed by non-strict replay for this arm only (DEVIATIONS.md); the 7 re-run. 92/92 clean.
  - RESULT (primary for this test): jitprompt_action@XL 0.652 vs jitprompt@XL 0.674, 5-6 discordant, exact McNemar p = 1.0. NOT supported. vs rag_bm25 6-7 (p = 1.0); vs full_prompt 9-2 (p = 0.065). False triggers 0.09 (jitprompt 0.11). Reached decision point 36/46 in both arms. Task pass 0.17 vs 0.11 (n.s.).
  - Wins/losses are scattered (won R10, R11, R12, R16, R24 once each; lost R02, R09, R14, R16, R19, R23), consistent with run-to-run noise.
  - Interpretation: in this benchmark the misses happen before any write call or with the rule already in context, so delivering rules at write time has nothing to act on. The literal matcher also misses rules written in prose. Per the overfitting discussion, no iteration on these rules.
- 2026-10-15: USER: test the stall fix (pinned core docs). PRE-REGISTERED before any run (design frozen):
  - Arm `jitprompt_pinned` @XL, k=2, 46 tasks, batch `pinned`: identical to `jitprompt` (same prompt, same MCP tools, namespace RULES_XL) plus a "Core procedures" block appended to the system prompt, containing two whole docs an admin would plausibly pin: `bank_accounts_(general)_009` (Retrieving Customer Account Information: the account-lookup tool) and `bank_accounts_(general)_042` (Human Agent Transfer Reason Codes). ~1K tokens. Models a jitprompt namespace returning pinned docs as MCP server `instructions`.
  - Choice of docs is informed by the stall analysis (that is the fix under test); no other doc was tried.
  - PRIMARY for this test: jitprompt_pinned@XL vs jitprompt@XL, exact McNemar on 46 triggered (task, trial) pairs; success = p < 0.05 in favour of pinning. Secondary: adherence on bank-account rules (16 triggered runs), account-lookup usage on bank-account tasks (32 runs), vs rag_bm25@XL and full_prompt@XL, false-trigger rate, task pass.
- 2026-10-15: Pinned-docs test (pre-registered above). 92/92 clean.
  - PRIMARY for this test: jitprompt_pinned@XL 0.826 vs jitprompt@XL 0.674, 9-2 discordant, exact McNemar p = 0.065. Pre-registered criterion (p < 0.05) NOT met; direction as predicted.
  - Secondary: vs rag_bm25@XL 0.826 vs 0.674, 8-1, p = 0.039; vs full_prompt@XL 16-1, p < 0.001. False triggers 0.09 (jitprompt 0.11). Task pass 0.14.
  - Mechanism: bank-account tasks, account lookup used 23/32 (jitprompt 9/32, BM25 15/32, full prompt 4/32); bank-account rules reached 13/16 and adhered 13/16 (jitprompt 7/16). Credit-card rules unchanged (25/30 vs 24/30).
  - XL with pinned core docs (0.83) is back at jitprompt's S level (0.85).
  - Caveats: the pinned docs were chosen from the stall analysis on these same tasks (in-sample); arms ran at different times; a held-out corpus is needed before calling it a finding.
- 2026-10-15: jitprompt 1.3.1 (server-side pinned docs) brief received. State found: production already reports serverInfo.version 1.3.1; RULES_XL already pinned by the user: doc 009 (381 est tokens) + doc 042 (1,512), total 1,949 / cap 2,000, both `included: true` (saved results/jitprompt/pins_XL.json). Tool descriptions identical to the 1.3.0 snapshot.
  - Harness: jitprompt_client.py captures `instructions`, client name per arm, `new_client()` for one MCP session per conversation (the old per-thread client would deliver in-band pins only to the first conversation per worker thread). retrieval_calls.jsonl rows now carry client_name, session_id, connects, server_version, starts_with_pins. New module pins_server.py: arms `jitprompt_sysprompt`, `jitprompt_inband`; run.py ARM_ENV sets JB_JP_SESSION=conversation and JB_JP_CLIENT_NAME.
  - Dry calls (no LLM): sysprompt client (`tau2-jitprompt-bench-sysprompt`) gets 5,261-char instructions, first search does NOT start with the block. Stock client (`tau2-jitprompt-bench`) gets the block on the first search or get_toc of a session, never again in that session; the block equals `instructions`. System prompt: jitprompt 6,138 chars, sysprompt 11,401 (prototype 10,469).
  - PRE-REGISTERED (before any run; design frozen):
    - Batch `pins131`, tier XL, k=2, 46 tasks, Haiku 5.5 agent / Sonnet 5.5 user as before. Server 1.3.1, pins as above, namespace RULES_XL, `catalog` profile.
    - `jitprompt_sysprompt` (primary): jitprompt prompt + the server's `instructions` verbatim in the system prompt; allowlisted client name, so no in-band copy.
    - `jitprompt_inband` (secondary): stock prompt and client; the server prepends the block to the first get_toc/search of each session.
    - PRIMARY: jitprompt_sysprompt@XL vs jitprompt@XL (1.3.0, unpinned, batch pilot, 0.674), exact McNemar on 46 triggered (task, trial) pairs; success = p < 0.05 in favour of sysprompt.
    - Secondary: jitprompt_inband vs jitprompt; sysprompt vs inband; replication of the prototype (jitprompt_pinned 0.826); vs rag_bm25 and full_prompt; bank-account lookup use (of 32) and bank-account rule adherence (of 16); in-band delivery rate (runs whose first jitprompt call carried the block; triggered runs that acted or transferred before any jitprompt call); false-trigger rate; task pass.
    - Caveats: pins chosen from this benchmark's stall analysis (in-sample); the baseline ran earlier on 1.3.0; the server block renders per-section ids, unlike the prototype.
    - Expected cost ≈ $0.9 per arm.
- 2026-10-15: jitprompt 1.3.1 RUNS DONE (batch pins131, 2 × 92 runs, 0 abnormal). Delivery verified: sysprompt block in all 92 system prompts, 0 in-band copies, client tau2-jitprompt-bench-sysprompt, server 1.3.1, 1 session per conversation; inband block on the first jitprompt call of all 92 conversations, never repeated.
  - PRIMARY (pre-registered): jitprompt_sysprompt@XL 0.717 vs jitprompt@XL (1.3.0 unpinned) 0.674, 8-6, p = 0.791. NOT met.
  - Secondary: jitprompt_inband@XL 0.848 vs jitprompt 9-1 (p = 0.021), vs rag_bm25 10-2 (p = 0.039), vs full_prompt 17-1. sysprompt vs inband 3-9 (p = 0.146); sysprompt vs prototype jitprompt_pinned 2-7 (p = 0.180); inband vs prototype 5-4 (p = 1.0). False triggers 0.04 in both arms (0.11 unpinned).
  - Mechanism replicated in both arms: account lookup used on bank-account tasks 30/32 (sysprompt), 29/32 (inband), vs 23/32 prototype and 9/32 unpinned. Bank-account rules adhered: 11/16 sysprompt, 15/16 inband (prototype 13, unpinned 7). Credit-card rules: 22/30 sysprompt, 24/30 inband (unpinned 24).
  - sysprompt's shortfall is spread over R02, R10, R16, R17 (no single rule), and isn't significant against inband or the prototype; with 46 pairs it can't be told from noise. Not iterated (pre-registration).
