# τ-Banking Rules: planted-rule adherence vs. corpus size

Does an agent with a whole instruction corpus in its prompt follow specific, conditional business
rules less reliably than one that retrieves only the relevant docs ("tokens are cheap, attention
isn't")? 23 planted rules (24 written, one dropped at the validity gate), each with a triggered and
a control task, on τ²-bench `banking_knowledge`; Claude Haiku 5.5 as the agent, three
knowledge-delivery arms (whole KB in the prompt, BM25, jitprompt) at two corpus sizes.

## Headline results
Rule adherence on triggered tasks at XL (716 docs, ~300K tokens), Haiku 5.5:

| Arm | Adherence |
|---|---|
| jitprompt | 85% |
| BM25 | 67% |
| Full KB in the prompt | 50% |

The 85% is jitprompt 1.3.1 with two core docs pinned, measured in a follow-up run; the pinned docs
were chosen after seeing the main run's failures. In the pre-registered run, jitprompt 1.3.0 without
pins scored 67%, tied with BM25, and beat the full prompt 8–0 on discordant pairs (exact McNemar
p = 0.008).

Full numbers and caveats: [REPORT.md](REPORT.md). The analysis was pre-registered in
[BRIEF.md](BRIEF.md) (the study brief); deviations are in [DEVIATIONS.md](DEVIATIONS.md).

## Layout
- `tau2-bench/jitprompt_rules/`: the harness (arms, rule checker, analysis), `rules.yaml`, rule docs
  and the 48 tasks (`tasks_rules.json`; the 2 for the dropped rule R05 are not scored). Runs inside
  an upstream tau2-bench checkout.
- `data/tiers/`: the S and XL corpora as fed to every arm, plus `manifest.json`.
- `results/`: per-run rows (`runs.csv`), summaries with CIs, McNemar tests (`paired.csv`), failure
  attribution, charts, the cost ledger and the logged retrieval calls.
- `RULES_SPEC.md`, `RULES_TABLE.md`: how the rules were written, and the full rule table.

Simulation transcripts are not included. `analyze.py` rebuilds `results/` from them, so it only
runs after you have produced your own; `chart.py` runs from `results/summary.csv` alone.

## Reproducing
```sh
git clone https://github.com/sierra-research/tau2-bench /tmp/tau2
git -C /tmp/tau2 checkout dd8757d4
rsync -a --exclude .git /tmp/tau2/ tau2-bench/
cd tau2-bench && uv sync
```
Put keys in `tau2-bench/.env`: `ANTHROPIC_API_KEY` for every arm; for the jitprompt arms,
`JITPROMPT_KEY_RULES_S` / `JITPROMPT_KEY_RULES_XL` (one jitprompt namespace per tier). Build those
namespaces with `ingest_jitprompt.py` (or `sync_namespace.py`), then run `jitprompt_snapshot.py`,
whose output the jitprompt arms read. Runs go through `jitprompt_rules/run.py`.

## License
MIT (see `LICENSE`). The tasks and corpora derive from τ²-bench, also MIT (see `LICENSE-tau2-bench`).
