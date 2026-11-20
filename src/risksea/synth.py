"""Synthetic Ethereum-like world with planted fraud clusters (milestone M1).

Used to build and test every component before real data. Roles:
  user      - ordinary accounts, unlabeled, trade with hubs/merchants/other users
  hub       - exchange-like, huge degree            -> label 0 (good)
  miner     - regular payouts to many users          -> label 0 (good)
  merchant  - ordinary-degree receivers              -> label 0 (good)
  mother    - fraud collector, bursts to mules       -> label 1 (bad)
  mule      - fraud cluster member, dense cluster    -> label 1 (bad), only a fraction labeled

Fraud nodes are dense cluster members with short, bursty activity; a handful of
bursty "decoy" users keep behavioral features from being trivially separating.
Everything is deterministic given the seed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TS_START = 1_438_269_988  # Ethereum genesis timestamp
BLOCK_SECONDS = 14

ROLES = ["user", "hub", "miner", "merchant", "mother", "mule"]


@dataclass
class World:
    tx: pd.DataFrame        # src,dst,block,ts,value,kind,token
    nodes: pd.DataFrame     # node,role,cluster
    labels: pd.DataFrame    # node,label (1 bad / 0 good), role
    n_blocks: int


def _kind_token(rng, n, p_eth=0.7, n_tokens=8):
    is_eth = rng.random(n) < p_eth
    kind = np.where(is_eth, "eth", "erc20")
    token = np.where(is_eth, -1, rng.integers(0, n_tokens, n))
    return kind, token


def _frame(src, dst, block, value, rng, p_eth=0.7):
    kind, token = _kind_token(rng, len(src), p_eth)
    return pd.DataFrame({
        "src": np.asarray(src, dtype=np.int64),
        "dst": np.asarray(dst, dtype=np.int64),
        "block": np.asarray(block, dtype=np.int64),
        "value": np.asarray(value, dtype=np.float64),
        "kind": kind,
        "token": token.astype(np.int64),
    })


def generate_world(n_blocks=100_000, n_users=3000, n_hubs=20, n_miners=20,
                   n_merchants=60, n_fraud_clusters=25, cluster_size=12,
                   n_decoys=15, seed=42, mule_label_frac=0.7,
                   fraud_window_frac=0.5) -> World:
    """fraud_window_frac: width of each cluster's activity window as a fraction of the chain.
    Large values + user-like amounts "camouflage" the fraud behaviorally, so only graph
    structure (dense cluster membership) separates it -- a deliberately hard dev fixture."""
    rng = np.random.default_rng(seed)

    # ---- node id layout -------------------------------------------------
    users = np.arange(0, n_users)
    hubs = np.arange(n_users, n_users + n_hubs)
    miners = np.arange(hubs[-1] + 1, hubs[-1] + 1 + n_miners)
    merchants = np.arange(miners[-1] + 1, miners[-1] + 1 + n_merchants)
    nxt = merchants[-1] + 1
    mothers = np.arange(nxt, nxt + n_fraud_clusters)
    nxt = mothers[-1] + 1
    n_mules_each = cluster_size - 1
    mules = np.arange(nxt, nxt + n_fraud_clusters * n_mules_each).reshape(n_fraud_clusters, n_mules_each)
    n_nodes = int(mules.max()) + 1

    role = np.empty(n_nodes, dtype=object)
    role[users] = "user"; role[hubs] = "hub"; role[miners] = "miner"; role[merchants] = "merchant"
    role[mothers] = "mother"; role[mules.ravel()] = "mule"
    cluster = np.full(n_nodes, -1, dtype=np.int64)
    cluster[mothers] = np.arange(n_fraud_clusters)
    for c in range(n_fraud_clusters):
        cluster[mules[c]] = c

    frames = []

    # ---- ordinary-style background traffic: preferential links to hubs/merchants/users ----
    hub_w = 1.0 / np.arange(1, n_hubs + 1) ** 0.8
    hub_w /= hub_w.sum()

    def background(actors, n_tx):
        u = np.repeat(actors, n_tx)
        m = len(u)
        pick = rng.random(m)
        other = np.where(
            pick < 0.5, rng.choice(hubs, m, p=hub_w),
            np.where(pick < 0.75, rng.choice(merchants, m), rng.choice(users, m)))
        other = np.where(other == u, (other + 1) % n_users, other)
        outgoing = rng.random(m) < 0.6
        src = np.where(outgoing, u, other)
        dst = np.where(outgoing, other, u)
        return _frame(src, dst, rng.integers(0, n_blocks, m), rng.lognormal(0.0, 1.0, m), rng)

    frames.append(background(users, 5 + rng.poisson(20, n_users)))
    # fraud nodes also behave like ordinary accounts on the side (behavioral camouflage)
    fraud_nodes = np.concatenate([mothers, mules.ravel()])
    frames.append(background(fraud_nodes, 3 + rng.poisson(18, len(fraud_nodes))))

    # ---- hubs: extra hub<->hub flow ------------------------------------
    m = n_hubs * 150
    a = rng.choice(hubs, m); b = rng.choice(hubs, m)
    keep = a != b
    frames.append(_frame(a[keep], b[keep], rng.integers(0, n_blocks, keep.sum()),
                         rng.lognormal(3.0, 1.0, keep.sum()), rng))

    # ---- miners: regular payouts at fixed cadence -----------------------
    for mi in miners:
        k = 250
        blocks = (np.arange(k) * (n_blocks // k) + rng.integers(0, 50, k)).clip(0, n_blocks - 1)
        frames.append(_frame(np.full(k, mi), rng.choice(users, k), blocks,
                             rng.lognormal(1.0, 0.3, k), rng))

    # ---- merchants: receive from users, sweep to hubs -------------------
    for me in merchants:
        k = 20
        frames.append(_frame(rng.choice(users, k), np.full(k, me),
                             rng.integers(0, n_blocks, k), rng.lognormal(0.0, 1.0, k), rng))
        k2 = 3
        frames.append(_frame(np.full(k2, me), rng.choice(hubs, k2, p=hub_w),
                             rng.integers(0, n_blocks, k2), rng.lognormal(0.0, 1.0, k2), rng))

    # ---- decoys: ordinary users with bursty behavior (not fraud) -------
    for d in rng.choice(users, n_decoys, replace=False):
        start = int(rng.integers(0, n_blocks * 0.9))
        k = 60
        blocks = (start + rng.integers(0, max(n_blocks // 40, 1), k)).clip(0, n_blocks - 1)
        frames.append(_frame(np.full(k, d), rng.choice(users, k), blocks,
                             rng.lognormal(-0.5, 0.5, k), rng))

    # ---- fraud clusters --------------------------------------------------
    for c in range(n_fraud_clusters):
        mom = mothers[c]
        cm = mules[c]
        win = max(int(n_blocks * fraud_window_frac), 1)
        start = int(rng.integers(0, max(n_blocks - win, 1)))
        rb = lambda k: start + rng.integers(0, win, k)
        # amounts follow the same lognormal(0, 1) as ordinary users (behavioral camouflage)
        # victims pay the mother
        nv = int(rng.integers(15, 40))
        frames.append(_frame(rng.choice(users, nv), np.full(nv, mom), rb(nv),
                             rng.lognormal(0.0, 1.0, nv), rng))
        # mother pays mules
        nb = int(len(cm) * rng.integers(6, 12))
        frames.append(_frame(np.full(nb, mom), rng.choice(cm, nb), rb(nb),
                             rng.lognormal(0.0, 1.0, nb), rng))
        # dense mule<->mule shuffling
        pairs = int(len(cm) * len(cm) * 0.6)
        a = rng.choice(cm, pairs); b = rng.choice(cm, pairs)
        keep = a != b
        frames.append(_frame(a[keep], b[keep], rb(keep.sum()),
                             rng.lognormal(0.0, 1.0, keep.sum()), rng))
        # cash-out to hubs
        nco = int(len(cm) * 2)
        frames.append(_frame(rng.choice(cm, nco), rng.choice(hubs, nco, p=hub_w), rb(nco),
                             rng.lognormal(0.0, 1.0, nco), rng))

    tx = pd.concat(frames, ignore_index=True)
    tx = tx[tx.src != tx.dst]
    tx["ts"] = TS_START + tx["block"] * BLOCK_SECONDS
    tx = tx.sort_values(["block", "src", "dst"], kind="mergesort").reset_index(drop=True)
    tx = tx[["src", "dst", "block", "ts", "value", "kind", "token"]]

    nodes = pd.DataFrame({"node": np.arange(n_nodes), "role": role, "cluster": cluster})

    # ---- labels (bad wins on conflict; here no conflicts by construction) ---
    bad_mules = mules.ravel()[rng.random(mules.size) < mule_label_frac]
    bad = np.concatenate([mothers, bad_mules])
    good = np.concatenate([hubs, miners, merchants])
    labels = pd.DataFrame({
        "node": np.concatenate([bad, good]),
        "label": np.concatenate([np.ones(len(bad), int), np.zeros(len(good), int)]),
    })
    labels["role"] = role[labels["node"].to_numpy()]
    labels = labels.sort_values("node").reset_index(drop=True)
    return World(tx=tx, nodes=nodes, labels=labels, n_blocks=n_blocks)
