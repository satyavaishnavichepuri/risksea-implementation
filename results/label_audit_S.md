# Label audit

- raw rows: 10,048 (invalid addresses: 4, duplicate rows dropped: 0)
- unique addresses: 10,044
- in more than one source: 0
- conflicts resolved to bad (paper rule): 0
- final: 5,713 bad / 4,331 good

| source | class | rows | unique addresses |
|---|---|---|---|
| block_miners | good | 3,959 | 3,959 |
| ethlabels_exchange | good | 372 | 372 |
| ethlabels_phish_hack | bad | 5,590 | 5,590 |
| ofac_sanctioned | bad | 123 | 123 |

## After restricting to addresses present in the graph
- 4,561 of 10,044 kept (5,483 never appear in the extracted transactions)
- usable labels: 481 bad / 4,080 good
