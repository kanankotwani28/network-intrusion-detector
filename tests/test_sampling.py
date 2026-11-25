import numpy as np
import pytest

from nids.data.sampling import largest_remainder_quotas, sample_indices_per_class


def test_quotas_sum_exactly_to_total():
    counts = {"Benign": 89291, "DDoS": 7462, "DoS": 2598, "Brute-Force": 649}
    quotas = largest_remainder_quotas(counts, 100_000)
    assert sum(quotas.values()) == 100_000


def test_quotas_proportional_to_counts():
    counts = {"A": 900, "B": 100}
    quotas = largest_remainder_quotas(counts, 10)
    assert quotas["A"] == 9
    assert quotas["B"] == 1


def test_largest_remainder_breaks_ties_by_fractional_part():
    # 3 classes, total not evenly divisible: verify sum is exact regardless.
    counts = {"A": 1, "B": 1, "C": 1}
    quotas = largest_remainder_quotas(counts, 10)
    assert sum(quotas.values()) == 10
    assert all(v in (3, 4) for v in quotas.values())


def test_sampling_without_replacement_respects_quota_and_seed():
    class_to_indices = {"A": np.arange(100), "B": np.arange(100, 150)}
    quotas = {"A": 10, "B": 5}
    out1 = sample_indices_per_class(class_to_indices, quotas, seed=42)
    out2 = sample_indices_per_class(class_to_indices, quotas, seed=42)
    assert len(out1["A"]) == 10
    assert len(out1["B"]) == 5
    assert len(set(out1["A"])) == 10  # no replacement
    np.testing.assert_array_equal(out1["A"], out2["A"])  # reproducible


def test_different_seed_gives_different_sample():
    class_to_indices = {"A": np.arange(1000)}
    quotas = {"A": 50}
    out1 = sample_indices_per_class(class_to_indices, quotas, seed=1)
    out2 = sample_indices_per_class(class_to_indices, quotas, seed=2)
    assert not np.array_equal(out1["A"], out2["A"])


def test_quota_exceeding_available_rows_raises():
    class_to_indices = {"A": np.arange(5)}
    quotas = {"A": 10}
    with pytest.raises(ValueError):
        sample_indices_per_class(class_to_indices, quotas, seed=42)
