import pandas as pd

from nids.evaluation.aggregation import aggregate_over_seeds


def test_aggregate_mean_and_std():
    df = pd.DataFrame(
        {
            "model": ["m1", "m1", "m1", "m2", "m2", "m2"],
            "seed": [42, 101, 202, 42, 101, 202],
            "macro_f1": [0.9, 1.0, 0.95, 0.5, 0.6, 0.55],
        }
    )
    out = aggregate_over_seeds(df, group_cols=["model"], value_cols=["macro_f1"])
    m1 = out[out["model"] == "m1"].iloc[0]
    assert m1["n_seeds"] == 3
    assert abs(m1["macro_f1_mean"] - 0.95) < 1e-9


def test_single_seed_std_is_zero_not_nan():
    df = pd.DataFrame({"model": ["m1"], "seed": [42], "macro_f1": [0.9]})
    out = aggregate_over_seeds(df, group_cols=["model"], value_cols=["macro_f1"])
    assert out["macro_f1_std"].iloc[0] == 0.0
