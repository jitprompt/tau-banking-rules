"""adherence_vs_corpus.png from results/summary.csv (run analyze.py first).

    uv run --no-sync python jitprompt_rules/chart.py
    uv run --no-sync python jitprompt_rules/chart.py --arms full_prompt jitprompt --out adherence_full_vs_jitprompt.png
    uv run --no-sync python jitprompt_rules/chart.py --xl-bars   (after analyze.py with all --extra arms)

One line per arm (S -> XL, x labelled with the full_kb prompt size), 95% bootstrap CI as
error bars, the two reference conditions as dashed horizontal lines. Palette: the dataviz
reference categorical slots 1-3 (validated light mode); every line is direct-labelled and
uses a distinct marker, so identity never rests on colour alone.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
ARMS = [("full_prompt", "Full prompt", "#2a78d6", "o"),
        ("rag_bm25", "BM25 RAG", "#eb6834", "s"),
        ("jitprompt", "jitprompt", "#1baf7a", "D")]
REFS = [("required_docs", "Gold docs (ceiling)"), ("no_rules", "No rules (floor)")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arms", nargs="+", default=[a[0] for a in ARMS])
    p.add_argument("--out", default="adherence_vs_corpus.png")
    p.add_argument("--xl-bars", action="store_true", help="instead: all arms at XL as bars (results/xl_arms.png)")
    args = p.parse_args()
    if args.xl_bars:
        return xl_bars()
    arms = [a for a in ARMS if a[0] in args.arms]
    rows = {(r["tier"], r["arm"]): r for r in csv.DictReader((OUT / "summary.csv").open())}
    manifest = json.loads((ROOT / "data/tiers/manifest.json").read_text())
    tiers = ["S", "XL"]
    ktok = {t: manifest["tiers"][t]["full_prompt"].get("prompt_tokens") for t in tiers}
    xlabels = [f"{t}\n{len(manifest['tiers'][t]['doc_ids'])} docs, {round(ktok[t] / 1000)}K tokens" if ktok[t] else t
               for t in tiers]

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    x = [0, 1]
    for j, (arm, label, color, marker) in enumerate(arms):
        dx = (j - (len(arms) - 1) / 2) * 0.045  # dodge so the CI bars don't overlap
        pts = [rows.get((t, arm)) for t in tiers]
        if not all(pts):
            continue
        y = [float(p["adherence"]) for p in pts]
        lo = [y[i] - float(p["adherence_ci_lo"]) for i, p in enumerate(pts)]
        hi = [float(p["adherence_ci_hi"]) - y[i] for i, p in enumerate(pts)]
        ax.errorbar([v + dx for v in x], y, yerr=[lo, hi], color=color, marker=marker, markersize=7, linewidth=2,
                    capsize=0, elinewidth=1.2, alpha=0.95, zorder=3,
                    markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.annotate(f"{label}  {y[-1]:.2f}", (x[-1] + 0.045, y[-1]), xytext=(10, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    for ref, label in REFS:
        r = rows.get(("ref", ref))
        if r and r["adherence"]:
            v = float(r["adherence"])
            ax.axhline(v, color=INK2, linestyle=(0, (4, 3)), linewidth=1.2, zorder=2)
            ax.annotate(f"{label}  {v:.2f}", (x[0], v), xytext=(-8, 4), textcoords="offset points",
                        ha="left", va="bottom", fontsize=8.5, color=INK2)
    ax.set_xticks(x, xlabels, fontsize=9, color=INK)
    ax.set_xlim(-0.15, 1.55)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Rule adherence (triggered tasks)", fontsize=9.5, color=INK)
    ax.set_title("Planted-rule adherence vs corpus size  (Haiku 5.5 agent, 95% CI over rules)",
                 fontsize=10.5, color=INK, loc="left")
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.tight_layout()
    out = OUT / args.out
    fig.savefig(out, facecolor=SURFACE)
    print(f"wrote {out}")



XL_BARS = [  # (arm, label); top to bottom
    ("full_prompt", "Full prompt (whole KB)"),
    ("rag_bm25", "BM25 RAG"),
    ("jitprompt", "jitprompt 1.3.0"),
    ("jitprompt_action", "jitprompt 1.3.0 + action hook*"),
    ("jitprompt_pinned", "jitprompt 1.3.0 + pins, harness prototype*"),
    ("jitprompt_sysprompt", "jitprompt 1.3.1, pins in system prompt*"),
    ("jitprompt_inband", "jitprompt 1.3.1, pins in-band*"),
]


def xl_bars(out_name: str = "xl_arms.png"):
    """All arms at XL as horizontal bars with 95% CIs; * = post-hoc follow-up arm."""
    rows = {(r["tier"], r["arm"]): r for r in csv.DictReader((OUT / "summary.csv").open())}
    arms = [(a, l) for a, l in XL_BARS if ("XL", a) in rows]
    fig, ax = plt.subplots(figsize=(7.6, 0.55 * len(arms) + 1.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    color = "#2a78d6"
    for i, (arm, label) in enumerate(arms):
        r = rows[("XL", arm)]
        v, lo, hi = float(r["adherence"]), float(r["adherence_ci_lo"]), float(r["adherence_ci_hi"])
        y = len(arms) - 1 - i
        ax.barh(y, v, height=0.56, color=color, zorder=3)
        ax.plot([lo, hi], [y, y], color=INK2, linewidth=1.2, zorder=4)
        ax.annotate(f"{v:.2f}", (v, y), xytext=(-6, 0), textcoords="offset points", ha="right", va="center",
                    fontsize=9, color=SURFACE, fontweight="bold", zorder=5)
    for ref, label in REFS:
        r = rows.get(("ref", ref))
        if r and r["adherence"]:
            v = float(r["adherence"])
            ax.axvline(v, color=INK2, linestyle=(0, (4, 3)), linewidth=1.1, zorder=2)
            ax.annotate(f"{label.split(' (')[0]} {v:.2f}", (v, len(arms) - 0.45), xytext=(-4, 0), textcoords="offset points",
                        ha="right" if v > 0.5 else "left", fontsize=8, color=INK2)
    ax.set_yticks(range(len(arms)), [l for _, l in reversed(arms)], fontsize=9, color=INK)
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("Rule adherence, triggered tasks (95% CI over rules)", fontsize=8.5, color=INK2)
    ax.set_title("All arms at XL: 716 docs, 304K tokens  (* = post-hoc follow-up)", fontsize=10, color=INK, loc="left")
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.tight_layout()
    fig.savefig(OUT / out_name, facecolor=SURFACE)
    print(f"wrote {OUT / out_name}")


if __name__ == "__main__":
    main()
