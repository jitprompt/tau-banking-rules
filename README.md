# τ-Banking Rules: planted-rule adherence vs. corpus size

Does an agent with a whole instruction corpus in its prompt follow specific, conditional business
rules less reliably than one that retrieves only the relevant docs ("tokens are cheap, attention
isn't")? 24 planted rules, each with a triggered and a control task, on τ²-bench `banking_knowledge`;
Claude Haiku 5.5 as the agent, three knowledge-delivery arms (whole KB in the prompt, BM25, jitprompt)
at two corpus sizes.

**Answer and numbers: [REPORT.md](REPORT.md).** The analysis was pre-registered in
[BRIEF.md](BRIEF.md) (the study brief); deviations are in [DEVIATIONS.md](DEVIATIONS.md) and the
run log in [PROGRESS.md](PROGRESS.md).

## Layout
- `tau2-bench/jitprompt_rules/`: the harness (arms, rule checker, analysis), `rules.yaml`, rule docs
  and the 48 tasks (`tasks_rules.json`). Runs inside an upstream tau2-bench checkout.
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
