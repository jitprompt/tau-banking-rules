"""Cost of one Haiku 5.5 call from its raw usage, and the run-wide ledger.

LiteLLM's `prompt_tokens` for Anthropic includes cache reads and writes, so the
uncached input is prompt - cache_read - cache_write. The pricing tier is chosen
by the whole prompt (uncached + cache read + cache write) against 100K tokens.
"""

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path(os.environ.get("JB_LEDGER", ROOT / "results/ledger.jsonl"))
HARD_STOP_USD = float(os.environ.get("JB_HARD_STOP_USD", "85"))

# $ per million tokens: (input, output, cache read, cache write 5m), and the prompt size
# above which a long-context rate applies (None: flat pricing).
PRICING = {
    "claude-haiku-5-5": {"threshold": 100_000,
                         "short": (0.10, 0.50, 0.01, 0.125), "long": (0.50, 2.50, 0.05, 0.625)},
    # No long-context surcharge is documented for Sonnet 5.5; checked against usage at the Sonnet floor check.
    "claude-sonnet-5-5": {"threshold": None, "short": (2.00, 10.00, 0.20, 2.50)},
}
DEFAULT_MODEL = "claude-haiku-5-5"


def usage_fields(usage) -> dict:
    get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    prompt = get("prompt_tokens") or 0
    cache_read = get("cache_read_input_tokens") or 0
    cache_write = get("cache_creation_input_tokens") or 0
    return {
        "input": prompt - cache_read - cache_write,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": get("completion_tokens") or 0,
        "prompt_total": prompt,
    }


def call_cost(u: dict, model: str = DEFAULT_MODEL) -> float:
    price = PRICING[model.removeprefix("anthropic/")]
    long = price["threshold"] is not None and u["prompt_total"] > price["threshold"]
    rin, rout, rcr, rcw = price["long" if long else "short"]
    return (u["input"] * rin + u["output"] * rout + u["cache_read"] * rcr + u["cache_write"] * rcw) / 1e6


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Append-only JSONL of every benchmark LLM call, shared by all processes."""

    def __init__(self, path: Path = LEDGER):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._spent = spent(self.path)

    @property
    def total(self) -> float:
        return self._spent

    def check(self):
        if self._spent >= HARD_STOP_USD:
            raise BudgetExceeded(f"spend ${self._spent:.2f} reached hard stop ${HARD_STOP_USD:.2f}")

    def record(self, usage, model: str = DEFAULT_MODEL, **labels) -> dict:
        u = usage_fields(usage)
        model = model.removeprefix("anthropic/")
        row = {"t": time.time(), "model": model, **labels, **u, "cost": call_cost(u, model)}
        with self._lock:
            self._spent += row["cost"]
            with self.path.open("a") as f:
                f.write(json.dumps(row) + "\n")
        return row


def spent(path: Path = LEDGER) -> float:
    if not path.exists():
        return 0.0
    with path.open() as f:
        return sum(json.loads(line)["cost"] for line in f if line.strip())


if __name__ == "__main__":
    print(f"${spent():.4f} spent per {LEDGER}")
