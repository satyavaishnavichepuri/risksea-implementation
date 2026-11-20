import numpy as np
import pandas as pd
import pytest

from risksea.config import load_config
from risksea.eval.metrics import compute_metrics, summarize
from risksea.model.risk import assemble, fit_eval, grouped_importance, multi_seed, split


def test_metrics_on_known_predictions():
    y = np.array([1, 1, 0, 0])
    m = compute_metrics(y, np.array([0.9, 0.4, 0.6, 0.1]), threshold=0.5)
    # predictions at 0.5: [1,0,1,0] -> TP=1 FP=1 FN=1
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5
    perfect = compute_metrics(y, np.array([0.9, 0.8, 0.2, 0.1]))
    assert perfect["roc_auc"] == 1.0 and perfect["pr_auc"] == pytest.approx(1.0)


def test_summarize_mean_std_ci():
    s = summarize([{"f1": 0.8}, {"f1": 0.6}, {"f1": 1.0}])
    assert s["f1"]["mean"] == pytest.approx(0.8)
    assert s["f1"]["std"] == pytest.approx(0.2)
    assert s["f1"]["ci95"] == pytest.approx(1.96 * 0.2 / np.sqrt(3))


def test_split_is_stratified_disjoint_and_seeded():
    labels = pd.DataFrame({"node": np.arange(100), "label": [1] * 20 + [0] * 80})
    tr, te = split(labels, seed=1, test_size=0.2)
    assert set(tr).isdisjoint(te) and len(tr) + len(te) == 100
    assert labels.set_index("node").loc[te, "label"].sum() == 4         # 20% of the 20 positives
    tr2, te2 = split(labels, seed=1, test_size=0.2)
    assert np.array_equal(te, te2)


def test_assemble_flags_missing_embeddings_and_selects_nodes():
    beh = pd.DataFrame({"eth_in_n": [1.0, 2.0, 3.0]}, index=[0, 1, 2])
    emb = np.arange(6, dtype=np.float32).reshape(3, 2)
    mask = np.array([True, False, True])
    X = assemble(beh, emb, mask, np.array([2, 1]))
    assert list(X.index) == [2, 1]
    assert list(X.columns) == ["eth_in_n", "n2v_0", "n2v_1", "has_n2v"]
    assert X.loc[2, "has_n2v"] == 1.0 and X.loc[1, "has_n2v"] == 0.0
    only_emb = assemble(None, emb, mask, np.array([0]))
    assert "eth_in_n" not in only_emb.columns


def test_model_learns_signal_and_importance_groups_sum_to_one():
    rng = np.random.default_rng(0)
    n = 300
    y = rng.integers(0, 2, n)
    nodes = np.arange(n)
    beh = pd.DataFrame({"eth_in_n": y * 2.0 + rng.normal(0, 0.5, n),
                        "erc20_in_n": rng.normal(0, 1, n)}, index=nodes)
    emb = rng.normal(0, 1, (n, 4)).astype(np.float32)
    mask = np.ones(n, bool)
    labels = pd.DataFrame({"node": nodes, "label": y})
    cfg = load_config(overrides={"model": {"n_estimators": 60, "n_seeds": 3}})
    X = assemble(beh, emb, mask, nodes)
    met, clf, proba, y_test = fit_eval(X, labels, cfg, seed=0)
    assert met["roc_auc"] > 0.9
    imp = grouped_importance(clf, X.columns)
    assert set(imp) == {"behavioral_eth", "behavioral_erc20", "node2vec"}
    assert sum(imp.values()) == pytest.approx(1.0)
    assert imp["behavioral_eth"] > imp["behavioral_erc20"]
    summ, runs = multi_seed(X, labels, cfg)
    assert len(runs) == 3 and summ["roc_auc"]["mean"] > 0.9


def test_assemble_compresses_huge_values_monotonically_and_stays_float32_safe():
    from risksea.model.risk import signed_log1p
    beh = pd.DataFrame({"eth_in_total": [0.0, 5.0, 1e30, 1e39, -3.0]}, index=[0, 1, 2, 3, 4])
    X = assemble(beh, None, None, np.array([0, 1, 2, 3, 4]))
    v = X["eth_in_total"].to_numpy()
    assert np.isfinite(v).all() and np.abs(v).max() < 1e3                      # no float32 overflow
    assert np.all(np.diff(v[[4, 0, 1, 2, 3]]) > 0)                              # order preserved incl. negatives
    assert signed_log1p(beh)["eth_in_total"][0] == 0.0
    raw = assemble(beh, None, None, np.array([3]), compress=False)
    assert raw["eth_in_total"].iloc[0] == 1e39                                  # opt-out leaves values alone
