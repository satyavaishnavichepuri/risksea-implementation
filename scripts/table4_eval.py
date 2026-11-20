"""Evaluate Table IV: propagation vs dynamic node2vec embeddings, node2vec features only (paper Sec IV-G).

    python scripts/table4_eval.py --tier S

At each checkpoint both methods are scored by the same random-forest protocol on the SAME addresses
(labeled addresses present at that block AND embedded by both methods, so neither is credited or penalised
for coverage). Dynamic is also scored on every present address to show its coverage advantage.
Metrics: PR-AUC / F1 mean +- 95% CI over seeds; checkpoints with too few bad addresses are reported but not scored.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.model.risk import assemble, multi_seed

ROOT = Path(__file__).resolve().parents[1]
MIN_PER_CLASS = 20


def score(emb, ok, labels, mask, cfg):
    y = labels.label.to_numpy()[mask]
    if (y == 1).sum() < MIN_PER_CLASS or (y == 0).sum() < MIN_PER_CLASS:
        return None
    pos = np.arange(int(mask.sum()))
    X = assemble(None, emb[mask], ok[mask], pos).drop(columns="has_n2v")      # flag dropped (leak, see D20 notes)
    summ, _ = multi_seed(X, pd.DataFrame({"node": pos, "label": y}), cfg)
    return {"n_bad": int((y == 1).sum()), "n_good": int((y == 0).sum()),
            "pr_auc": summ["pr_auc"], "f1": summ["f1"], "roc_auc": summ["roc_auc"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    a = ap.parse_args()
    cfg = load_config()
    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    res = ROOT / "results" / f"real_{a.tier}"
    dyn, prop = np.load(res / "table4_dynamic.npz"), np.load(res / "table4_propagation.npz")
    meta_d = json.loads((res / "table4_dynamic.json").read_text())
    meta_p = json.loads((res / "table4_propagation.json").read_text())
    rows = []
    for cp in meta_d["checkpoints"]:
        present = dyn[f"present_{cp}"]
        both = present & dyn[f"ok_{cp}"] & prop[f"ok_{cp}"]
        r = {"checkpoint": cp, "labeled_present": int(present.sum()),
             "dynamic_embedded": int((present & dyn[f'ok_{cp}']).sum()),
             "propagation_embedded": int((present & prop[f'ok_{cp}']).sum()),
             "both": int(both.sum()), "n_bad_both": int((both & (labels.label.to_numpy() == 1)).sum()),
             "propagation_seconds": meta_p["per_checkpoint"][str(cp)]["seconds_cumulative"],
             "dynamic_seconds": meta_d["per_checkpoint"][str(cp)]["seconds_cumulative"],
             "propagation_core_coverage": meta_p["per_checkpoint"][str(cp)].get("core_coverage_of_universe")}
        r["propagation"] = score(prop[f"emb_{cp}"], prop[f"ok_{cp}"], labels, both, cfg)
        r["dynamic"] = score(dyn[f"emb_{cp}"], dyn[f"ok_{cp}"], labels, both, cfg)
        r["dynamic_all_present"] = score(dyn[f"emb_{cp}"], dyn[f"ok_{cp}"], labels, present & dyn[f"ok_{cp}"], cfg)
        rows.append(r)
        fmt = lambda s: "n/a (too few bad)" if s is None else \
            f"PR-AUC {s['pr_auc']['mean']:.3f}±{s['pr_auc']['ci95']:.3f}  F1 {s['f1']['mean']:.3f}±{s['f1']['ci95']:.3f}  (bad {s['n_bad']}, good {s['n_good']})"
        print(f"checkpoint {cp:>9,}: present {r['labeled_present']}, embedded by dynamic {r['dynamic_embedded']} / "
              f"propagation {r['propagation_embedded']} / both {r['both']}")
        print(f"   propagation        : {fmt(r['propagation'])}")
        print(f"   dynamic (same set) : {fmt(r['dynamic'])}")
        print(f"   dynamic (all)      : {fmt(r['dynamic_all_present'])}")
    (res / "table4_results.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
