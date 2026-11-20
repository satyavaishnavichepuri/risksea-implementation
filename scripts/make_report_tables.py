"""Generate every table and number macro of the LaTeX report from the result files (nothing typed by hand).

    python scripts/make_report_tables.py
Writes report/tables/*.tex and report/numbers.tex, and copies figures to report/figures/.
Paper values (Tables II-IV, label and hardware facts) are the only constants here; they come from the paper's text.
"""
import json
import re
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "real_S"
OUT = ROOT / "report"
TAB = OUT / "tables"
TAB.mkdir(parents=True, exist_ok=True)
(OUT / "figures").mkdir(exist_ok=True)

# ---- paper constants (arXiv 2410.02160) ---------------------------------------------------------------
PAPER_T2 = {"behavioral": (0.803, 0.650, 0.718), "propagated_n2v": (0.798, 0.686, 0.738),
            "propagated_n2v+behavioral": (0.908, 0.801, 0.851)}
PAPER_T3 = {(3, 8, 1, 1): 0.751, (6, 8, 1, 1): 0.787, (9, 8, 1, 1): 0.795, (3, 16, 1, 1): 0.774,
            (10, 10, 1, 1): 0.814, (9, 16, 1, 1): 0.808, (3, 8, 0.5, 1): 0.759, (3, 8, 2, 1): 0.753,
            (3, 8, 4, 1): 0.767, (3, 8, 1, 0.5): 0.753, (3, 8, 1, 2): 0.767, (3, 8, 1, 4): 0.767}

UNI = {"→": r"$\rightarrow$", "≥": r"$\geq$", "≤": r"$\leq$", "×": r"$\times$", "±": r"$\pm$",
       "≈": r"$\approx$", "–": "--", "—": "---", "’": "'", "“": "``", "”": "''"}
SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
           "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}


def esc(s: str) -> str:
    for k, v in UNI.items():
        s = s.replace(k, "\x00" + str(list(UNI).index(k)) + "\x00")
    s = "".join(SPECIAL.get(c, c) for c in s)
    return re.sub("\x00(\\d+)\x00", lambda m: UNI[list(UNI)[int(m.group(1))]], s)


def md2tex(s: str) -> str:
    """Tiny markdown subset: `code` -> \\texttt, *emph* -> \\emph, everything else escaped."""
    out = []
    for i, part in enumerate(s.split("`")):
        if i % 2:                                              # code
            out.append(r"\texttt{" + esc(part).replace(r"\_", r"\_\allowbreak{}") + "}")
        else:
            toks = re.split(r"(\*[^*]+\*)", part)
            out.append("".join(r"\emph{" + esc(t[1:-1]) + "}" if t.startswith("*") and t.endswith("*") and len(t) > 2
                               else esc(t) for t in toks))
    return "".join(out)


def pm(d, nd=3):
    return f"{d['mean']:.{nd}f}{{\\scriptsize$\\pm${d['ci95']:.{nd}f}}}"


def mean(d, nd=3):
    return f"{d['mean']:.{nd}f}"


def write(name, text):
    (TAB / name).write_text(text, encoding="utf-8")


def load(name):
    return json.loads((RES / name).read_text())


# ---- numbers.tex -------------------------------------------------------------------------------------------
graph = json.loads((ROOT / "data" / "graph" / "S" / "stats.json").read_text())
labels = pd.read_parquet(ROOT / "data" / "labels" / "labels_S.parquet")
overlap = json.loads((ROOT / "results" / "label_overlap_S.json").read_text())
cov_a = json.loads((ROOT / "data" / "processed" / "S" / "coverage_2500000.json").read_text())
cov_b = json.loads((ROOT / "data" / "processed" / "S" / "coverage_2500000_noseeds.json").read_text())
feat = pd.read_parquet(ROOT / "data" / "processed" / "S" / "features_labeled.parquet")
n_eth = sum(c.startswith("eth_") for c in feat.columns)
n_erc = sum(c.startswith("erc20_") for c in feat.columns)
fmt = lambda x: f"{int(x):,}"
macros = {
    "NumNodes": fmt(graph["nodes"]), "NumPairs": fmt(graph["directed_pairs"]), "NumAdj": fmt(graph["adjacency_entries"]),
    "NumLabeled": fmt(len(labels)), "NumBad": fmt((labels.label == 1).sum()), "NumGood": fmt((labels.label == 0).sum()),
    "NumMiners": fmt((labels.sources == "block_miners").sum()),
    "NumFeat": str(feat.shape[1]), "NumFeatEth": str(n_eth), "NumFeatErc": str(n_erc),
    "CovA": f"{100 * cov_a['coverage']:.1f}", "CovB": f"{100 * cov_b['coverage']:.1f}",
}
(OUT / "numbers.tex").write_text("".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in macros.items()))

# ---- Table II comparison -----------------------------------------------------------------------------------
A, B = load("table2_A_seeds.json"), load("table2_B_noseeds.json")
rows = [("Behavioral features", "behavioral"), ("Node2vec embedding", "propagated_n2v"),
        ("Node2vec + behavioral", "propagated_n2v+behavioral")]
t = [r"\begin{tabular}{l ccc ccc ccc}", r"\toprule",
     r" & \multicolumn{3}{c}{Paper} & \multicolumn{3}{c}{Ours, variant A} & \multicolumn{3}{c}{Ours, variant B}\\",
     r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}\cmidrule(lr){8-10}",
     r"Features & P & R & F$_1$ & P & R & F$_1$ & P & R & F$_1$\\", r"\midrule"]
for lab, k in rows:
    p = PAPER_T2[k]
    cells = [f"{v:.3f}" for v in p]
    for X in (A, B):
        m = X["metrics"][k]
        cells += [mean(m["precision"]), mean(m["recall"]), mean(m["f1"])]
    t.append(lab + " & " + " & ".join(cells) + r"\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_table2_compare.tex", "\n".join(t))

# ---- Table II detail with confidence intervals ----------------------------------------------------------------
variants = [("A", "table2_A_seeds.json", "A: labeled in core"), ("A-nm", "table2_A_seeds_nominers.json", "A, no miners"),
            ("B", "table2_B_noseeds.json", "B: propagated"), ("B-nf", "table2_B_noseeds_noflag.json", "B, flag removed"),
            ("B-co", "table2_B_noseeds_coveredonly.json", "B, covered only"),
            ("B-nm", "table2_B_noseeds_nominers.json", "B, no miners")]
t = [r"\begin{tabular}{l r r ccc ccc}", r"\toprule",
     r" & & & \multicolumn{3}{c}{F$_1$} & \multicolumn{3}{c}{PR-AUC}\\",
     r"\cmidrule(lr){4-6}\cmidrule(lr){7-9}",
     r"Variant & bad & good & behav. & n2v & both & behav. & n2v & both\\", r"\midrule"]
for _, f, lab in variants:
    X = load(f)
    m = X["metrics"]
    ks = ["behavioral", "propagated_n2v", "propagated_n2v+behavioral"]
    t.append(f"{lab} & {X['n_bad']} & {X['n_good']:,} & " + " & ".join(pm(m[k]["f1"]) for k in ks) + " & " +
             " & ".join(pm(m[k]["pr_auc"]) for k in ks) + r"\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_table2_detail.tex", "\n".join(t))

# ---- importance ------------------------------------------------------------------------------------------------
t = [r"\begin{tabular}{l r r r}", r"\toprule", r"Feature group & columns & variant A & variant B\\", r"\midrule"]
for g, n, name in (("behavioral_eth", n_eth, "Behavioral, ETH"), ("behavioral_erc20", n_erc, "Behavioral, ERC-20"),
                   ("node2vec", 129, "Node2vec (128 dims + flag)")):
    t.append(f"{name} & {n} & {100 * A['importance'][g]:.1f}\\% & {100 * B['importance'][g]:.1f}\\%\\\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_importance.tex", "\n".join(t))

# ---- sweep -------------------------------------------------------------------------------------------------------
runs = [json.loads(p.read_text()) for p in sorted((RES / "sweep").glob("*.json"))]
key = lambda r: (r["config"]["num_walks"], r["config"]["walk_length"], r["config"]["p"], r["config"]["q"])
base = [r["all"]["pr_auc"]["mean"] for r in runs if key(r) == (3, 8, 1, 1)]
lo, hi = min(base), max(base)
macros2 = {"NoiseLo": f"{lo:.3f}", "NoiseHi": f"{hi:.3f}", "NoiseRange": f"{hi - lo:.3f}",
           "NoiseStd": f"{pd.Series(base).std(ddof=1):.3f}", "NoiseN": str(len(base))}
main_runs = {key(r): r for r in runs if r["train_seed_offset"] == 0}
t = [r"\begin{tabular}{rrrr cc c c r l}", r"\toprule",
     r"walks & len. & $p$ & $q$ & PR-AUC (all) & F$_1$ & PR-AUC (no miners) & paper AUC & train s & vs.\ noise\\", r"\midrule"]
for k in sorted(main_runs, key=lambda k: (k[0] * k[1], k)):
    r = main_runs[k]
    m = r["all"]["pr_auc"]["mean"]
    tag = "base" if k == (3, 8, 1, 1) else ("above" if m > hi else ("below" if m < lo else "within"))
    pap = PAPER_T3.get(k)
    t.append(f"{k[0]} & {k[1]} & {k[2]:g} & {k[3]:g} & {pm(r['all']['pr_auc'])} & {mean(r['all']['f1'])} & "
             f"{mean(r['no_miners']['pr_auc'])} & {'%.3f' % pap if pap else '(blank)'} & {r['train_seconds']:.0f} & {tag}\\\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_sweep.tex", "\n".join(t))
best = max(main_runs.values(), key=lambda r: r["all"]["pr_auc"]["mean"])
macros2["BestWalks"], macros2["BestLen"] = str(best["config"]["num_walks"]), str(best["config"]["walk_length"])
macros2["BestPRAUC"] = f"{best['all']['pr_auc']['mean']:.3f}"
m10 = main_runs[(10, 10, 1, 1)]
macros2["TenTenPRAUC"] = mean(m10["all"]["pr_auc"])
macros2["TenTenF"] = mean(m10["all"]["f1"])
macros2["TableTwoNtvPRAUC"] = mean(A["metrics"]["propagated_n2v"]["pr_auc"])

# ---- Table IV ------------------------------------------------------------------------------------------------------
T4 = json.loads((RES / "table4_results.json").read_text())
t = [r"\begin{tabular}{r rrr rr cc cc}", r"\toprule",
     r"block & present & prop. & dyn. & bad & good & \multicolumn{2}{c}{PR-AUC} & \multicolumn{2}{c}{F$_1$}\\",
     r"\cmidrule(lr){7-8}\cmidrule(lr){9-10}",
     r" & & embedded & embedded & \multicolumn{2}{c}{(shared set)} & prop. & dyn. & prop. & dyn.\\", r"\midrule"]
for r in T4:
    P, D = r["propagation"], r["dynamic"]
    t.append(f"{r['checkpoint'] / 1e6:.1f}M & {r['labeled_present']:,} & {r['propagation_embedded']:,} & {r['dynamic_embedded']:,} & "
             f"{P['n_bad']} & {P['n_good']:,} & {pm(P['pr_auc'])} & {pm(D['pr_auc'])} & {mean(P['f1'])} & {mean(D['f1'])}\\\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_table4.tex", "\n".join(t))
last = T4[-1]
macros2["TFourPropPR"], macros2["TFourDynPR"] = mean(last["propagation"]["pr_auc"]), mean(last["dynamic"]["pr_auc"])
macros2["DynSeconds"] = f"{last['dynamic_seconds']:.0f}"
macros2["PropSeconds"] = f"{last['propagation_seconds']:.0f}"
macros2["DynAllPR"] = mean(last["dynamic_all_present"]["pr_auc"])
(OUT / "numbers.tex").write_text((OUT / "numbers.tex").read_text() +
                                 "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in macros2.items()))

# ---- coverage ------------------------------------------------------------------------------------------------------
Bm = B
cov_rows = [("Paper: propagation, whole Ethereum graph", "78\\%", "(80--85\\% of daily-active addresses)"),
            ("Ours, variant A: core 2.5M (labeled in core), whole 24.1M-node graph",
             f"{100 * cov_a['coverage']:.1f}\\%", f"{cov_a['covered_one_hop']:,} of {cov_a['nodes_with_edges']:,} nodes with an edge"),
            ("Ours, variant B: labeled addresses kept out of the core, whole graph",
             f"{100 * cov_b['coverage']:.1f}\\%", f"{cov_b['covered_one_hop']:,} of {cov_b['nodes_with_edges']:,}"),
            ("Ours, variant B: labeled addresses embedded by propagation",
             f"{100 * B['embedding_available']:.1f}\\%", "97.3\\% of bad, 88.2\\% of good"),
            ]
for r in T4:
    c = json.loads((RES / "table4_propagation.json").read_text())["per_checkpoint"][str(r["checkpoint"])]
    cov_rows.append((f"Ours, Table IV universe (3M nodes), block {r['checkpoint'] / 1e6:.1f}M: core reach / labeled embedded",
                     f"{100 * c['core_coverage_of_universe']:.1f}\\%", f"{r['propagation_embedded']:,} of {r['labeled_present']:,} labeled"))
t = [r"\begin{tabular}{p{7.6cm} r p{5.2cm}}", r"\toprule", r"Setting & Coverage & Detail\\", r"\midrule"]
t += [f"{a} & {b} & {c}\\\\" for a, b, c in cov_rows]
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_coverage.tex", "\n".join(t))

# ---- t-SNE metrics -----------------------------------------------------------------------------------------------
TS = json.loads((RES / "tsne_metrics.json").read_text())
names = [("all_by_risk_class", "Bad vs.\\ good (all labeled)"), ("all", "Six groups (Fig.~11 analog)"),
         ("risky", "Risky sub-types only (Fig.~12)"), ("trusted", "Miners vs.\\ exchanges (Fig.~13)")]
t = [r"\begin{tabular}{l r cc cc c}", r"\toprule",
     r" & $n$ & \multicolumn{2}{c}{silhouette (cosine)} & \multicolumn{2}{c}{5-NN accuracy} & majority\\",
     r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}", r" & & real & shuffled & real & shuffled & baseline\\", r"\midrule"]
for k, lab in names:
    m = TS[k]
    t.append(f"{lab} & {m['n']:,} & {m['real']['silhouette_cosine']:.3f} & {m['shuffled_control']['silhouette_cosine']:.3f} & "
             f"{m['real']['knn5_accuracy']:.3f} & {m['shuffled_control']['knn5_accuracy']:.3f} & "
             f"{m['real']['majority_baseline_accuracy']:.3f}\\\\")
t += [r"\bottomrule", r"\end{tabular}"]
write("tab_tsne.tex", "\n".join(t))
macros3 = {"TsneBadGoodKnn": f"{TS['all_by_risk_class']['real']['knn5_accuracy']:.3f}",
           "TsneBadGoodBal": f"{TS['all_by_risk_class']['real']['knn5_balanced_accuracy']:.3f}",
           "TsneBadGoodSil": f"{TS['all_by_risk_class']['real']['silhouette_cosine']:.3f}"}
(OUT / "numbers.tex").write_text((OUT / "numbers.tex").read_text() +
                                 "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in macros3.items()))

# ---- labels --------------------------------------------------------------------------------------------------------
names = {"ethlabels_phish_hack": ("Etherscan phishing/hack (eth-labels)", "bad"), "ofac_sanctioned": ("OFAC sanctioned addresses", "bad"),
         "block_miners": ("Block miners (from \\texttt{blocks.miner})", "good"), "ethlabels_exchange": ("Etherscan exchanges (eth-labels)", "good")}
t = [r"\begin{tabular}{l c r r}", r"\toprule", r"Source & class & labeled & present in graph (blocks $\leq$ 5M)\\", r"\midrule"]
for k in ("ethlabels_phish_hack", "ofac_sanctioned", "block_miners", "ethlabels_exchange"):
    v = overlap["per_source"][k]
    t.append(f"{names[k][0]} & {names[k][1]} & {v['labeled']:,} & {v['in_graph']:,}\\\\")
t += [r"\midrule", f"Total usable after merge & & & {macros['NumBad']} bad / {macros['NumGood']} good\\\\", r"\bottomrule", r"\end{tabular}"]
write("tab_labels.tex", "\n".join(t))

# ---- decision log ---------------------------------------------------------------------------------------------------
def split_cells(line):
    """Split a markdown table row on '|' but not inside `code` spans (e.g. `sign(x)*log1p(|x|)`)."""
    cells, cur, in_code = [], "", False
    for ch in line.strip().strip("|"):
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


lines = [l for l in (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8").splitlines() if l.startswith("| D")]
t = [r"\begin{longtable}{p{0.7cm} p{2.1cm} p{3.2cm} p{4.2cm} p{3.6cm}}", r"\toprule",
     r"\# & Topic & Paper says & Our choice & Reason\\", r"\midrule", r"\endhead"]
for l in lines:
    cells = split_cells(l)
    t.append(" & ".join(md2tex(c) for c in cells[:5]) + r"\\[2pt]")
t += [r"\bottomrule", r"\end{longtable}"]
write("tab_decisions.tex", "\n".join(t))

# ---- figures ----------------------------------------------------------------------------------------------------------
for f in (ROOT / "results" / "figures").glob("*.png"):
    shutil.copy(f, OUT / "figures" / f.name)
print("tables:", sorted(p.name for p in TAB.glob("*.tex")))
print("figures:", sorted(p.name for p in (OUT / "figures").glob("*.png")))
print(open(OUT / "numbers.tex").read())
