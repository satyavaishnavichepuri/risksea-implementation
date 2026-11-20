"""Summarise the Table III sweep: markdown table + PR-curve figures (analogs of paper Figs 5-9).

    python scripts/sweep_report.py --tier S

Reads results/real_<tier>/sweep/*.json. Writes results/real_<tier>/sweep_summary.md and results/figures/sweep_*.png.
The paper's Table III has blank cells and Figs 8-9 appear to carry swapped p/q captions (decision D10); here
every figure is labelled by the parameter that was actually varied. The paper's own "AUC" metric is not defined
precisely, so absolute values are not comparable; compare orderings and trends.
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# paper Table III AUC values (blank cells omitted); key = (walks, length, p, q)
PAPER = {(3, 8, 1, 1): 0.751, (6, 8, 1, 1): 0.787, (9, 8, 1, 1): 0.795, (3, 16, 1, 1): 0.774,
         (10, 10, 1, 1): 0.814, (9, 16, 1, 1): 0.808, (3, 8, 0.5, 1): 0.759, (3, 8, 2, 1): 0.753,
         (3, 8, 4, 1): 0.767, (3, 8, 1, 0.5): 0.753, (3, 8, 1, 2): 0.767, (3, 8, 1, 4): 0.767}

FIGS = [  # (file, title, list of (walks, length, p, q), legend labels)
    ("sweep_fig5_walks", "Varying number of walks (length 8)", [(3, 8, 1, 1), (6, 8, 1, 1), (9, 8, 1, 1)], "{0} walks"),
    ("sweep_fig6_length", "Varying walk length (3 walks)", [(3, 4, 1, 1), (3, 8, 1, 1), (3, 16, 1, 1)], "length {1}"),
    ("sweep_fig7_joint", "Varying walks and length", [(3, 8, 1, 1), (6, 8, 1, 1), (10, 10, 1, 1), (9, 16, 1, 1)], "{0} walks x {1}"),
    ("sweep_fig8_p", "Varying return parameter p (3 walks, length 8)",
     [(3, 8, v, 1) for v in (0.25, 0.5, 1, 2, 4)], "p={2:g}"),
    ("sweep_fig9_q", "Varying in-out parameter q (3 walks, length 8)",
     [(3, 8, 1, v) for v in (0.25, 0.5, 1, 2, 4)], "q={3:g}"),
]


def key_of(r):
    c = r["config"]
    return (c["num_walks"], c["walk_length"], c["p"], c["q"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    a = ap.parse_args()
    res_dir = ROOT / "results" / f"real_{a.tier}"
    runs = [json.loads(p.read_text()) for p in sorted((res_dir / "sweep").glob("*.json"))]
    main_runs = {key_of(r): r for r in runs if r["train_seed_offset"] == 0}
    noise = [r for r in runs if key_of(r) == (3, 8, 1, 1)]                       # base config, every training seed

    lines = [f"# Table III sweep (tier {a.tier}): {len(runs)} trainings, node2vec features only", ""]
    if len(noise) >= 2:
        v = np.array([r["all"]["pr_auc"]["mean"] for r in noise])
        lines += [f"**Training noise:** the base configuration (3 walks, length 8, p=q=1) was trained {len(noise)} times "
                  f"with different seeds: PR-AUC {', '.join(f'{x:.3f}' for x in v)} "
                  f"(std {v.std(ddof=1):.3f}, range {v.max() - v.min():.3f}). "
                  "Differences between configurations smaller than this range cannot be told apart from retraining noise.", ""]
    else:
        lines += ["**Training noise:** not yet measured (fewer than two base-configuration trainings).", ""]
    lines += ["| walks | length | p | q | PR-AUC (all) | F1 (all) | PR-AUC (no miners) | paper AUC | train s |",
              "|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(main_runs, key=lambda k: (k[0] * k[1], k)):
        r = main_runs[k]
        s, f, nm = r["all"]["pr_auc"], r["all"]["f1"], r["no_miners"]["pr_auc"]
        pap = PAPER.get(k)
        lines.append(f"| {k[0]} | {k[1]} | {k[2]:g} | {k[3]:g} | {s['mean']:.3f} ± {s['ci95']:.3f} | {f['mean']:.3f} | "
                     f"{nm['mean']:.3f} | {'%.3f' % pap if pap else '(blank)'} | {r['train_seconds']:.0f} |")
    if main_runs:
        best = max(main_runs.values(), key=lambda r: r["all"]["pr_auc"]["mean"])
        lines += ["", f"**Best configuration by PR-AUC:** walks={best['config']['num_walks']}, length={best['config']['walk_length']}, "
                      f"p={best['config']['p']:g}, q={best['config']['q']:g} "
                      f"(PR-AUC {best['all']['pr_auc']['mean']:.3f}). The paper's best: 10 walks, length 10, p=q=1."]
    (res_dir / "sweep_summary.md").write_text("\n".join(lines) + "\n")

    figdir = ROOT / "results" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    for fname, title, keys, label in FIGS:
        fig, ax = plt.subplots(figsize=(5.5, 4.2))
        drawn = 0
        for k in keys:
            r = main_runs.get(k)
            if r is None:
                continue
            ax.plot(r["pr_curve"]["recall"], r["pr_curve"]["precision"], label=label.format(*k) +
                    f" (PR-AUC {r['all']['pr_auc']['mean']:.3f})")
            drawn += 1
        if not drawn:
            plt.close(fig)
            continue
        ax.set(xlabel="Recall", ylabel="Precision", title=title, xlim=(0, 1), ylim=(0, 1.02))
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(figdir / f"{fname}.png", dpi=130)
        plt.close(fig)
    print("\n".join(lines))
    print("figures:", sorted(p.name for p in figdir.glob("sweep_*.png")))


if __name__ == "__main__":
    main()
