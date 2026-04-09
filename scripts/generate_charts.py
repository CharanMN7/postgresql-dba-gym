#!/usr/bin/env python3
"""Generate benchmark charts for the README from evaluation data.

Run once from the repo root:
    python scripts/generate_charts.py

Outputs:
    screenshots/benchmark_leaderboard.png
    screenshots/benchmark_heatmap.png
    screenshots/medium_pass_rate.png
"""

from __future__ import annotations

import pathlib

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

BG = "#1a1a2e"
FG = "#e0e0e0"
GRID = "#2a2a4a"

TIER_COLORS = {
    "S": "#ffd700",
    "A": "#4fc3f7",
    "A−": "#78909c",
    "C": "#ef5350",
}

MODELS_RANKED = [
    ("gpt-4o-mini",    "S",  5.000),
    ("gpt-3.5-turbo",  "A−", 4.865),
    ("Gemma-3-27B",    "A",  4.825),
    ("Llama-3.3-70B",  "A",  4.825),
    ("Llama-4-Scout",  "A",  4.825),
    ("Qwen2.5-72B",    "A",  4.825),
    ("Llama-3.1-8B",   "C",  3.530),
]

HEATMAP_MODELS = [
    "gpt-4o-mini",
    "Gemma-3-27B",
    "Llama-3.3-70B",
    "Llama-4-Scout",
    "Qwen2.5-72B",
    "gpt-3.5-turbo",
    "Llama-3.1-8B",
]
TASKS = ["easy", "medium", "hard", "expert", "master"]
HEATMAP_DATA = np.array([
    [1.00, 1.000, 1.000, 1.000, 1.000],
    [0.99, 0.865, 0.990, 0.990, 0.990],
    [0.99, 0.865, 0.990, 0.990, 0.990],
    [0.99, 0.865, 0.990, 0.990, 0.990],
    [0.99, 0.865, 0.990, 0.990, 0.990],
    [1.00, 0.865, 1.000, 1.000, 1.000],
    [0.99, 0.550, 0.010, 0.990, 0.990],
])

MEDIUM_PASS = [
    ("gpt-4o-mini",    100),
    ("Gemma-3-27B",    100),
    ("Llama-3.3-70B",   67),
    ("Llama-4-Scout",   50),
    ("Qwen2.5-72B",     50),
    ("gpt-3.5-turbo",   33),
    ("Llama-3.1-8B",     0),
]


def _apply_theme(ax: plt.Axes) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, which="both")
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)


def chart_leaderboard() -> None:
    names = [m[0] for m in MODELS_RANKED]
    scores = [m[2] for m in MODELS_RANKED]
    colors = [TIER_COLORS[m[1]] for m in MODELS_RANKED]

    names.reverse()
    scores.reverse()
    colors.reverse()

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    _apply_theme(ax)

    y = np.arange(len(names))
    bars = ax.barh(y, scores, color=colors, height=0.6, edgecolor="none")

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_width() + 0.04, bar.get_y() + bar.get_height() / 2,
            f"{score:.3f}", va="center", ha="left",
            color=FG, fontsize=10, fontweight="bold",
        )

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=11)
    ax.set_xlim(0, 5.6)
    ax.set_xlabel("Best Aggregate Score (out of 5.0)", fontsize=11)
    ax.set_title("Model Leaderboard", fontsize=14, fontweight="bold", pad=12)
    ax.xaxis.grid(True, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "benchmark_leaderboard.png", dpi=180, facecolor=BG)
    plt.close(fig)
    print(f"  -> {OUT_DIR / 'benchmark_leaderboard.png'}")


def chart_heatmap() -> None:
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "score", ["#b71c1c", "#ff8f00", "#2e7d32"], N=256,
    )

    fig, ax = plt.subplots(figsize=(8, 5))
    fig.patch.set_facecolor(BG)
    _apply_theme(ax)

    im = ax.imshow(HEATMAP_DATA, cmap=cmap, aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(np.arange(len(TASKS)))
    ax.set_xticklabels(TASKS, fontsize=11)
    ax.set_yticks(np.arange(len(HEATMAP_MODELS)))
    ax.set_yticklabels(HEATMAP_MODELS, fontsize=11)
    ax.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False)

    for i in range(len(HEATMAP_MODELS)):
        for j in range(len(TASKS)):
            val = HEATMAP_DATA[i, j]
            text_color = "#ffffff" if val < 0.5 else "#000000"
            ax.text(
                j, i, f"{val:.2f}", ha="center", va="center",
                color=text_color, fontsize=10, fontweight="bold",
            )

    ax.set_title(
        "Best Per-Task Score by Model", fontsize=14, fontweight="bold", pad=16,
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.ax.tick_params(colors=FG)
    cbar.outline.set_edgecolor(GRID)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "benchmark_heatmap.png", dpi=180, facecolor=BG)
    plt.close(fig)
    print(f"  -> {OUT_DIR / 'benchmark_heatmap.png'}")


def chart_medium_pass() -> None:
    names = [m[0] for m in MEDIUM_PASS]
    rates = [m[1] for m in MEDIUM_PASS]

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "pass", ["#b71c1c", "#ff8f00", "#2e7d32"], N=256,
    )
    colors = [cmap(r / 100) for r in rates]

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor(BG)
    _apply_theme(ax)

    x = np.arange(len(names))
    bars = ax.bar(x, rates, color=colors, width=0.55, edgecolor="none")

    for bar, rate in zip(bars, rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
            f"{rate}%", ha="center", va="bottom",
            color=FG, fontsize=11, fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10, rotation=25, ha="right")
    ax.set_ylim(0, 115)
    ax.set_ylabel("Pass Rate (%)", fontsize=11)
    ax.set_title(
        "Medium Task (Schema Migration) — Pass Rate",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "medium_pass_rate.png", dpi=180, facecolor=BG)
    plt.close(fig)
    print(f"  -> {OUT_DIR / 'medium_pass_rate.png'}")


if __name__ == "__main__":
    print("Generating charts...")
    chart_leaderboard()
    chart_heatmap()
    chart_medium_pass()
    print("Done.")
