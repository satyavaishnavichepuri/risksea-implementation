"""Label assembly and audit (M3).

Each source is turned into rows (address, label, source, raw_label) where label is
1 = "bad" (illicit activity) or 0 = "good" (exchange, miner, government...). Per the paper
(Sec III-A), an address with conflicting labels from different sources keeps the HIGH
risk label. Every step is counted so the label audit can be reviewed before any model
result is trusted.
"""
from __future__ import annotations

import re

import pandas as pd

_ADDR = re.compile(r"^0x[0-9a-f]{40}$")


def normalize_address(a) -> str | None:
    """Lowercase 0x + 40 hex chars, or None if it is not a valid Ethereum address."""
    if not isinstance(a, str):
        return None
    a = a.strip().lower()
    return a if _ADDR.match(a) else None


def standardize(df: pd.DataFrame, source: str, label: int, address_col: str = "address",
                raw_label_col: str | None = None) -> pd.DataFrame:
    """One source -> standard frame. Invalid addresses are kept (address=None) so they are counted."""
    out = pd.DataFrame({
        "address": df[address_col].map(normalize_address),
        "label": int(label),
        "source": source,
        "raw_label": df[raw_label_col].astype(str) if raw_label_col else "",
    })
    return out


def merge_labels(frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Merge sources. Returns (labels[address,label,n_sources,sources,conflict], audit dict)."""
    raw = pd.concat(frames, ignore_index=True)
    invalid = int(raw["address"].isna().sum())
    valid = raw.dropna(subset=["address"])
    audit = {
        "raw_rows": int(len(raw)),
        "invalid_addresses": invalid,
        "per_source": {s: {"rows": int(len(g)), "unique_addresses": int(g.address.nunique()),
                           "label": int(g.label.iloc[0])}
                       for s, g in valid.groupby("source")},
    }
    audit["duplicate_rows_dropped"] = int(len(valid) - len(valid.drop_duplicates(["address", "source"])))
    valid = valid.drop_duplicates(["address", "source"])

    g = valid.groupby("address")
    merged = pd.DataFrame({
        "label": g["label"].max(),                       # bad wins
        "n_sources": g["source"].nunique(),
        "sources": g["source"].agg(lambda s: ",".join(sorted(set(s)))),
        "n_label_values": g["label"].nunique(),
    }).reset_index()
    merged["conflict"] = merged["n_label_values"] > 1
    merged = merged.drop(columns="n_label_values")

    audit["unique_addresses"] = int(len(merged))
    audit["conflicts_resolved_to_bad"] = int(merged["conflict"].sum())
    audit["final_bad"] = int((merged.label == 1).sum())
    audit["final_good"] = int((merged.label == 0).sum())
    # overlap between sources (addresses present in more than one source)
    audit["addresses_in_multiple_sources"] = int((merged.n_sources > 1).sum())
    return merged, audit


def restrict_to_graph(merged: pd.DataFrame, address_to_node: dict) -> tuple[pd.DataFrame, dict]:
    """Keep labeled addresses that exist in the graph; attach node ids; report what was dropped."""
    node = merged["address"].map(address_to_node)
    kept = merged[node.notna()].copy()
    kept["node"] = node[node.notna()].astype("int64").to_numpy()
    info = {"before": int(len(merged)), "in_graph": int(len(kept)),
            "dropped_not_in_graph": int(len(merged) - len(kept)),
            "final_bad": int((kept.label == 1).sum()), "final_good": int((kept.label == 0).sum())}
    return kept.reset_index(drop=True), info


def audit_markdown(audit: dict, graph_info: dict | None = None) -> str:
    lines = ["# Label audit", "",
             f"- raw rows: {audit['raw_rows']:,} (invalid addresses: {audit['invalid_addresses']:,}, "
             f"duplicate rows dropped: {audit['duplicate_rows_dropped']:,})",
             f"- unique addresses: {audit['unique_addresses']:,}",
             f"- in more than one source: {audit['addresses_in_multiple_sources']:,}",
             f"- conflicts resolved to bad (paper rule): {audit['conflicts_resolved_to_bad']:,}",
             f"- final: {audit['final_bad']:,} bad / {audit['final_good']:,} good", "",
             "| source | class | rows | unique addresses |", "|---|---|---|---|"]
    for s, v in sorted(audit["per_source"].items()):
        lines.append(f"| {s} | {'bad' if v['label'] else 'good'} | {v['rows']:,} | {v['unique_addresses']:,} |")
    if graph_info:
        lines += ["", "## After restricting to addresses present in the graph",
                  f"- {graph_info['in_graph']:,} of {graph_info['before']:,} kept "
                  f"({graph_info['dropped_not_in_graph']:,} never appear in the extracted transactions)",
                  f"- usable labels: {graph_info['final_bad']:,} bad / {graph_info['final_good']:,} good"]
    return "\n".join(lines) + "\n"
