"""Benchmark cases with published answers (from the book, Chapter 8) used to validate the tracer.

Each case has a source address, a time window, and what the book reports. The addresses of the sources are printed in the
book's footnotes; the book reports where the funds ended up, so a correct tracer should rediscover those destinations.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def ts(date: str) -> int:
    return calendar.timegm(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timetuple())


@dataclass
class Case:
    id: str
    title: str
    source: str
    start: str
    end: str
    story: str
    expected: list = field(default_factory=list)       # what the book reports (names + notes)
    expect_names: list = field(default_factory=list)   # substrings we look for among traced destinations
    reference: str = ""

    @property
    def t0(self) -> int:
        return ts(self.start)

    @property
    def t1(self) -> int:
        return ts(self.end)

    def to_json(self) -> dict:
        d = asdict(self)
        d.update(t0=self.t0, t1=self.t1)
        return d


CASES = {
    "cryptopia_2019": Case(
        id="cryptopia_2019", title="Cryptopia exchange hack (May 2019)",
        source="0xd4e79226f1e5a7a28abb58f4704e53cd364e8d11", start="2019-05-14", end="2019-06-28",
        story="About 30.8K ETH was stolen from the Cryptopia exchange. The book reports that the funds reached EtherDelta "
              "within two hops and later cashed out at Yobit.net and OKEx.",
        expected=["EtherDelta targets within 2 hops (about 10K ETH)", "Yobit.net (about 1.4K ETH, 4 hops)",
                  "OKEx (about 18.5K ETH, 4 hops)"],
        expect_names=["EtherDelta", "Yobit", "OKEx"],
        reference="Blockchain Transaction Data Analytics, Ch. 8, Sec. 8.4.4.1"),
    "phishing_2018": Case(
        id="phishing_2018", title="Phishing-labeled wallet to exchange deposits (2018)",
        source="0x5457bb4430d8b8d1a3708576100aef0e027c5b9b", start="2018-06-29", end="2018-08-13",
        story="A real address that Etherscan users tagged as phishing (label Fake_Phishing1951) moved about 2,450 ETH in mid-2018. "
              "There is NO published answer for this case: it was picked from public labels because its trace reaches exchange "
              "deposit addresses, so it shows the attribution rule on real data. Treat the result as an investigative lead, not a verdict.",
        expected=[], expect_names=[],
        reference="Public Etherscan label via eth-labels; selected by us (selection bias disclosed)"),
    "kucoin_2020": Case(
        id="kucoin_2020", title="KuCoin exchange hack (September 2020)",
        source="0xeb31973e0febf3e3d7058234a5ebbae1ab4b8c23", start="2020-09-25", end="2020-11-10",
        story="The hacker's wallet received ETH from KuCoin and moved most of it into Tornado Cash. The book reports about "
              "13.8K ETH reaching the 100 ETH pool, where tracing must stop because a mixer breaks the on-chain link.",
        expected=["Tornado Cash 100 ETH pool (about 13.8K ETH)", "trace should stop at the mixer and say so"],
        expect_names=["Tornado"],
        reference="Blockchain Transaction Data Analytics, Ch. 8, Sec. 8.4.4.2"),
}
