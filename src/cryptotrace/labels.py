"""Label store: which addresses are exchanges, mixers, sanctioned, known-bad. Every label carries its provenance.

Sources (all public, loaded from local files):
  * eth-labels `exchange` list (Etherscan-derived; terms-of-use caveat is tracked in docs/decisions.md D19)
  * eth-labels `phish-hack` list (known bad)
  * OFAC SDN Ethereum list (sanctioned)
  * a small curated list below: mixers and the addresses printed in the book's case studies.
Tornado Cash pool addresses are curated by hand because the OFAC list no longer includes them (delisted 2025);
they were verified on-chain: each receives only one fixed denomination (0.1 / 1 / 10 / 100 ETH).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from cryptotrace.models import Label

CURATED = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": Label("mixer", "Tornado Cash (0.1 ETH pool)", "curated; on-chain verified"),
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": Label("mixer", "Tornado Cash (1 ETH pool)", "curated; on-chain verified"),
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": Label("mixer", "Tornado Cash (10 ETH pool)", "curated; on-chain verified"),
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": Label("mixer", "Tornado Cash (100 ETH pool)", "curated; on-chain verified"),
    # Curated from public knowledge and NOT verified on-chain by this project: the EtherDelta DEX contract. In the Cryptopia
    # trace 99.98% of the funds enter this address in 500-1000 ETH batches, matching the book's "EtherDelta within 2 hops".
    "0x8d12a197cb00d4747a1fe03395095ce2a5cc6819": Label("dex", "EtherDelta (DEX contract)", "curated; unverified on-chain"),
    # printed in the book's case studies (Ch. 8): the exchange that received Cryptopia's stolen ETH
    "0xf5bec430576ff1b82e44ddb5a1c93f6f9d0884f3": Label("exchange", "Yobit.net", "book Ch.8 + eth-labels"),
}


class LabelStore:
    def __init__(self):
        self._labels: dict[str, Label] = {}

    def add(self, addr: str, label: Label, overwrite: bool = False):
        a = addr.lower().strip()
        if overwrite or a not in self._labels:
            self._labels[a] = label

    def get(self, addr: str):
        return self._labels.get(addr.lower())

    def kind(self, addr: str):
        l = self.get(addr)
        return l.kind if l else None

    def __len__(self):
        return len(self._labels)

    def counts(self) -> dict:
        out: dict = {}
        for l in self._labels.values():
            out[l.kind] = out.get(l.kind, 0) + 1
        return out

    @classmethod
    def from_files(cls, root: str | Path) -> "LabelStore":
        root = Path(root)
        s = cls()
        for a, l in CURATED.items():
            s.add(a, l, overwrite=True)
        ex = root / "ethlabels_raw" / "exchange_all.csv"
        if ex.exists():
            for r in pd.read_csv(ex, dtype=str).itertuples():
                name = r.nameTag if isinstance(r.nameTag, str) and r.nameTag.strip() else "Exchange (unnamed)"
                s.add(r.address, Label("exchange", name, "eth-labels exchange (Etherscan-derived)"))
        bad = root / "ethlabels_raw" / "phish-hack_all.csv"
        if bad.exists():
            for r in pd.read_csv(bad, dtype=str).itertuples():
                name = r.nameTag if isinstance(r.nameTag, str) and r.nameTag.strip() else "Reported phishing/hack"
                s.add(r.address, Label("bad", name, "eth-labels phish-hack (Etherscan-derived)"))
        of = root / "ofac_raw" / "sanctioned_addresses_ETH.txt"
        if of.exists():
            for a in of.read_text().split():
                s.add(a, Label("sanctioned", "OFAC-sanctioned address", "OFAC SDN via 0xB10C list"))
        return s
