import numpy as np
import pandas as pd

from nids.features.ratios import compute_ratios


def test_ratios_never_nan_or_inf_with_zero_denominators():
    df = pd.DataFrame(
        {
            "IN_BYTES": [0, 100, 50],
            "OUT_BYTES": [0, 0, 20],
            "IN_PKTS": [0, 0, 5],
            "OUT_PKTS": [0, 0, 2],
            "NUM_PKTS_UP_TO_128_BYTES": [0, 0, 3],
            "NUM_PKTS_128_TO_256_BYTES": [0, 0, 1],
            "NUM_PKTS_256_TO_512_BYTES": [0, 0, 1],
            "NUM_PKTS_512_TO_1024_BYTES": [0, 0, 1],
            "NUM_PKTS_1024_TO_1514_BYTES": [0, 0, 1],
        }
    )
    out = compute_ratios(df, bin_denominator="in_out_pkts")
    assert np.isfinite(out.to_numpy()).all()
    assert (out.to_numpy() >= 0).all()


def test_bpp_in_matches_formula():
    df = pd.DataFrame(
        {
            "IN_BYTES": [1000], "OUT_BYTES": [500], "IN_PKTS": [10], "OUT_PKTS": [5],
            "NUM_PKTS_UP_TO_128_BYTES": [2], "NUM_PKTS_128_TO_256_BYTES": [2],
            "NUM_PKTS_256_TO_512_BYTES": [2], "NUM_PKTS_512_TO_1024_BYTES": [2],
            "NUM_PKTS_1024_TO_1514_BYTES": [2],
        }
    )
    out = compute_ratios(df)
    assert out["BPP_IN"].iloc[0] == 100.0
    assert out["BPP_OUT"].iloc[0] == 100.0
    assert out["DIR_RATIO"].iloc[0] == 1000 / 501


def test_bin_shares_sum_to_one_when_bins_cover_denominator():
    df = pd.DataFrame(
        {
            "IN_BYTES": [1], "OUT_BYTES": [1], "IN_PKTS": [6], "OUT_PKTS": [4],
            "NUM_PKTS_UP_TO_128_BYTES": [2], "NUM_PKTS_128_TO_256_BYTES": [2],
            "NUM_PKTS_256_TO_512_BYTES": [2], "NUM_PKTS_512_TO_1024_BYTES": [2],
            "NUM_PKTS_1024_TO_1514_BYTES": [2],
        }
    )
    out = compute_ratios(df, bin_denominator="in_out_pkts")
    share_cols = ["SHARE_128", "SHARE_128_256", "SHARE_256_512", "SHARE_512_1024", "SHARE_1024_1514"]
    assert np.isclose(out[share_cols].iloc[0].sum(), 1.0)


def test_bin_denominator_choice_changes_shares():
    df = pd.DataFrame(
        {
            "IN_BYTES": [1], "OUT_BYTES": [1], "IN_PKTS": [5], "OUT_PKTS": [5],
            "NUM_PKTS_UP_TO_128_BYTES": [5], "NUM_PKTS_128_TO_256_BYTES": [0],
            "NUM_PKTS_256_TO_512_BYTES": [0], "NUM_PKTS_512_TO_1024_BYTES": [0],
            "NUM_PKTS_1024_TO_1514_BYTES": [0],
        }
    )
    out_single = compute_ratios(df, bin_denominator="in_pkts")
    out_both = compute_ratios(df, bin_denominator="in_out_pkts")
    assert out_single["SHARE_128"].iloc[0] == 1.0
    assert out_both["SHARE_128"].iloc[0] == 0.5
