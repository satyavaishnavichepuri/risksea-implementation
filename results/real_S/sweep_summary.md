# Table III sweep (tier S): 18 trainings, node2vec features only

**Training noise:** the base configuration (3 walks, length 8, p=q=1) was trained 4 times with different seeds: PR-AUC 0.865, 0.854, 0.846, 0.841 (std 0.010, range 0.024). Differences between configurations smaller than this range cannot be told apart from retraining noise.

| walks | length | p | q | PR-AUC (all) | F1 (all) | PR-AUC (no miners) | paper AUC | train s |
|---|---|---|---|---|---|---|---|---|
| 3 | 4 | 1 | 1 | 0.693 ± 0.019 | 0.598 | 0.988 | (blank) | 97 |
| 3 | 8 | 0.25 | 1 | 0.821 ± 0.016 | 0.732 | 0.996 | (blank) | 175 |
| 3 | 8 | 0.5 | 1 | 0.846 ± 0.019 | 0.748 | 0.994 | 0.759 | 176 |
| 3 | 8 | 1 | 0.25 | 0.870 ± 0.008 | 0.805 | 0.995 | (blank) | 174 |
| 3 | 8 | 1 | 0.5 | 0.847 ± 0.019 | 0.745 | 0.993 | 0.753 | 180 |
| 3 | 8 | 1 | 1 | 0.865 ± 0.014 | 0.782 | 0.994 | 0.751 | 169 |
| 3 | 8 | 1 | 2 | 0.850 ± 0.006 | 0.746 | 0.995 | 0.767 | 174 |
| 3 | 8 | 1 | 4 | 0.857 ± 0.012 | 0.770 | 0.995 | 0.767 | 170 |
| 3 | 8 | 2 | 1 | 0.855 ± 0.018 | 0.782 | 0.992 | 0.753 | 175 |
| 3 | 8 | 4 | 1 | 0.861 ± 0.021 | 0.768 | 0.993 | 0.767 | 175 |
| 3 | 16 | 1 | 1 | 0.871 ± 0.014 | 0.781 | 0.993 | 0.774 | 375 |
| 6 | 8 | 1 | 1 | 0.915 ± 0.006 | 0.841 | 0.994 | 0.787 | 317 |
| 9 | 8 | 1 | 1 | 0.929 ± 0.008 | 0.863 | 0.993 | 0.795 | 461 |
| 10 | 10 | 1 | 1 | 0.947 ± 0.008 | 0.893 | 0.992 | 0.814 | 675 |
| 9 | 16 | 1 | 1 | 0.938 ± 0.013 | 0.852 | 0.991 | 0.808 | 1105 |

**Best configuration by PR-AUC:** walks=10, length=10, p=1, q=1 (PR-AUC 0.947). The paper's best: 10 walks, length 10, p=q=1.
