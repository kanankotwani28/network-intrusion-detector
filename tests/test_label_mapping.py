import numpy as np
import pandas as pd

from nids.data.label_mapping import (
    ATTACK_CODES,
    BENIGN,
    BENIGN_CODE,
    CLASS_TO_CODE,
    EXCLUDED_LABELS,
    INCLUDED_LABEL_MAP,
    build_label_mapping_log,
    label_treatment,
    map_attack_labels,
)


def test_all_appendix_b_included_labels_map_correctly():
    expected = {
        "Benign": "Benign",
        "DDOS attack-HOIC": "DDoS",
        "DDOS attack-LOIC-UDP": "DDoS",
        "DDoS attacks-LOIC-HTTP": "DDoS",
        "DoS attacks-GoldenEye": "DoS",
        "DoS attacks-Hulk": "DoS",
        "DoS attacks-SlowHTTPTest": "DoS",
        "DoS attacks-Slowloris": "DoS",
        "FTP-BruteForce": "Brute-Force",
        "SSH-Bruteforce": "Brute-Force",
    }
    assert INCLUDED_LABEL_MAP == expected
    series = pd.Series(list(expected.keys()))
    codes = map_attack_labels(series)
    for label, code in zip(series, codes):
        assert code == CLASS_TO_CODE[expected[label]]


def test_excluded_labels_map_to_minus_one_not_silently_mapped():
    excluded = pd.Series(list(EXCLUDED_LABELS.keys()))
    codes = map_attack_labels(excluded)
    assert np.all(codes == -1)
    for label in EXCLUDED_LABELS:
        assert label_treatment(label) == "excluded"


def test_unknown_label_is_flagged_not_guessed():
    assert label_treatment("Totally-Unseen-Label") == "unknown"
    codes = map_attack_labels(pd.Series(["Totally-Unseen-Label"]))
    assert codes[0] == -1


def test_no_substring_confusion_between_similar_labels():
    # "Brute Force -Web" must never be mapped like "FTP-BruteForce".
    codes = map_attack_labels(pd.Series(["Brute Force -Web", "FTP-BruteForce"]))
    assert codes[0] == -1
    assert codes[1] == CLASS_TO_CODE["Brute-Force"]


def test_benign_and_attack_codes_disjoint():
    assert BENIGN_CODE not in ATTACK_CODES
    assert CLASS_TO_CODE[BENIGN] == BENIGN_CODE


def test_label_mapping_log_reports_every_known_label():
    raw_counts = {"Benign": 10, "DDOS attack-HOIC": 5, "Weird-Label": 2}
    log = build_label_mapping_log(raw_counts, {"Benign": {0}, "DDOS attack-HOIC": {1}, "Weird-Label": {1}})
    assert "Weird-Label" in set(log["original_label"])
    row = log[log["original_label"] == "Weird-Label"].iloc[0]
    assert row["treatment"] == "unknown"
    row_benign = log[log["original_label"] == "Benign"].iloc[0]
    assert row_benign["binary_label_consistent"]
