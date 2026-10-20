"""Run benchmark batches: one tau2 process per (arm, tier).

    uv run --no-sync python jitprompt_rules/run.py --batch floor --arms no_knowledge required_docs \
        --tasks task_002 task_004 --trials 1 --est-per-run 0.01

Each (arm, tier) runs `jitprompt_rules.tau2_entry run ...` in its own process
(upstream caches KB documents globally, so tiers must not share a process) and
saves to data/simulations/jb_<batch>_<arm>_<tier>/. Before each process the
runner refuses to start if spend so far + the projected cost of that process
would exceed the budget cap; inside, tau2_entry stops new LLM calls at the
hard stop.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_tiers import TASK_IDS  # noqa: E402  (all 48 rule tasks, from tasks_rules.json)
from cost import spent  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MODEL = "anthropic/claude-haiku-5-5"
LLM_ARGS = {
    "thinking": {"type": "disabled"},
    "cache_control_injection_points": [
        {"location": "message", "role": "system"},
        {"location": "message", "index": -1},
    ],
}
ARMS = {  # arm -> (tau2 retrieval config, fixed KB tier or None = take --tiers)
    "full_prompt": ("full_kb", None),
    "rag_bm25": ("bm25_grep", None),
    "jitprompt": ("jitprompt", None),
    "jitprompt_action": ("jitprompt_action", None),  # jitprompt + pre-call action hook (action_hook.py)
    "jitprompt_pinned": ("jitprompt_pinned", None),  # jitprompt + pinned core docs in the system prompt (pinned.py)
    "jitprompt_sysprompt": ("jitprompt_sysprompt", None),  # 1.3.1 server pins via MCP instructions (pins_server.py)
    "jitprompt_inband": ("jitprompt_inband", None),  # 1.3.1 server pins delivered in-band (pins_server.py)
    # References: gold docs inlined per task. required_docs reads rule-bearing docs (tier S);
    # no_rules reads S_norules (standalone rule docs absent, buried docs in original text).
    "required_docs": ("golden_retrieval", "S"),
    "no_rules": ("golden_retrieval", "S_norules"),
    "no_knowledge": ("no_knowledge", "S"),
}
BUDGET_CAP = 90.0
# Per-arm environment for the jitprompt 1.3.1 arms: one MCP session per conversation, and the
# client name the server sees (the sysprompt name is on the server's instructions allowlist).
ARM_ENV = {
    "jitprompt_sysprompt": {"JB_JP_SESSION": "conversation", "JB_JP_CLIENT_NAME": "tau2-jitprompt-bench-sysprompt"},
    "jitprompt_inband": {"JB_JP_SESSION": "conversation", "JB_JP_CLIENT_NAME": "tau2-jitprompt-bench"},
}


def save_name(batch: str, arm: str, tier: str | None) -> str:
    return f"jr_{batch}_{arm}" + (f"_{tier}" if tier else "")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", required=True)
    p.add_argument("--arms", nargs="+", required=True, choices=list(ARMS))
    p.add_argument("--tiers", nargs="+", default=["S", "XL"])
    p.add_argument("--tasks", nargs="+", default=TASK_IDS)
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--seed", type=int, default=300)
    p.add_argument("--agent-model", default=MODEL, choices=[MODEL, "anthropic/claude-sonnet-5-5"],
                   help="agent model")
    p.add_argument("--user-model", default="anthropic/claude-sonnet-5-5", choices=[MODEL, "anthropic/claude-sonnet-5-5"],
                   help="user simulator model; thinking is always off for it")
    p.add_argument("--agent-thinking", choices=["off", "adaptive"], default="off",
                   help="agent only; 'off' is `disabled` on Haiku and `between_tools` on Sonnet 5.5 "
                        "(which rejects `disabled`). The user simulator always runs with thinking disabled")
    p.add_argument("--est-per-run", type=float, required=True,
                   help="projected $ per simulation, used for the pre-flight budget check")
    args = p.parse_args()

    jobs = []
    for arm in args.arms:
        config, fixed = ARMS[arm]
        for tier in (args.tiers if fixed is None else [fixed]):
            jobs.append((arm, config, tier, fixed is None))

    for arm, config, tier, tiered in jobs:
        n_runs = len(args.tasks) * args.trials
        projected = spent() + n_runs * args.est_per_run
        if projected > BUDGET_CAP:
            sys.exit(f"STOP before {arm}/{tier}: spent ${spent():.2f} + projected "
                     f"${n_runs * args.est_per_run:.2f} > cap ${BUDGET_CAP:.2f}")
        name = save_name(args.batch, arm, tier if tiered else None)
        def off(model):  # Sonnet 5.5 rejects `disabled`; `between_tools` is its thinking-off mode
            return "between_tools" if "sonnet-5-5" in model else "disabled"
        agent_args = {**LLM_ARGS, "thinking": {"type": off(args.agent_model) if args.agent_thinking == "off" else "adaptive"}}
        user_args = {**LLM_ARGS, "thinking": {"type": off(args.user_model)}}
        cmd = [
            sys.executable, "-m", "jitprompt_rules.tau2_entry", "run",
            "--domain", "banking_knowledge", "--retrieval-config", config,
            "--agent-llm", args.agent_model, "--user-llm", args.user_model,
            "--agent-llm-args", json.dumps(agent_args), "--user-llm-args", json.dumps(user_args),
            "--task-ids", *args.tasks, "--num-trials", str(args.trials),
            "--max-concurrency", str(args.concurrency), "--seed", str(args.seed),
            "--save-to", name, "--auto-resume",
        ]
        env = {**os.environ, "JB_ARM": arm, "JB_BATCH": args.batch, **ARM_ENV.get(arm, {})}
        env["JB_TIER"] = tier
        before = spent()
        print(f"=== {name}: {n_runs} runs (spent so far ${before:.2f})", flush=True)
        log = REPO.parent / "results/logs" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            if arm == "full_prompt" and len(args.tasks) > 1:
                # Pre-warm: one task alone writes the KB prefix to the prompt cache, so the
                # concurrent tasks that follow read it instead of each paying the cache write.
                # Same --num-trials as the batch, so with --auto-resume it runs the first task's
                # next pending trial (a 1-trial warm-up would be a no-op once trial 1 exists).
                warm = cmd[:cmd.index("--task-ids") + 1] + [args.tasks[0]] + cmd[cmd.index("--num-trials"):]
                warm[warm.index("--max-concurrency") + 1] = "1"
                subprocess.run(warm, cwd=REPO, env=env, stdout=f, stderr=subprocess.STDOUT)
            rc = subprocess.run(cmd, cwd=REPO, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
        print(f"    exit {rc}, batch cost ${spent() - before:.3f}, total ${spent():.2f}", flush=True)
        if rc != 0:
            sys.exit(f"{name} failed (exit {rc}); see {log}")


if __name__ == "__main__":
    main()
