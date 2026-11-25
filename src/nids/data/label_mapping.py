"""Exact original-label -> project-class mapping (proposal Appendix B).

Labels are matched by exact string equality only. No substring, case-folding
or whitespace normalisation is applied, because e.g. ``"Brute Force -Web"``
must never be confused with ``"FTP-BruteForce"``. Any label not listed in
:data:`ALL_KNOWN_LABELS` is reported as *unknown* instead of being guessed.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

BENIGN: Final[str] = "Benign"
DDOS: Final[str] = "DDoS"
DOS: Final[str] = "DoS"
BRUTE_FORCE: Final[str] = "Brute-Force"

# Fixed class order -> integer code used as the model target ``y``.
PROJECT_CLASSES: Final[list[str]] = [BENIGN, DDOS, DOS, BRUTE_FORCE]
CLASS_TO_CODE: Final[dict[str, int]] = {c: i for i, c in enumerate(PROJECT_CLASSES)}
BENIGN_CODE: Final[int] = CLASS_TO_CODE[BENIGN]
ATTACK_CODES: Final[list[int]] = [CLASS_TO_CODE[c] for c in (DDOS, DOS, BRUTE_FORCE)]

INCLUDED_LABEL_MAP: Final[dict[str, str]] = {
    "Benign": BENIGN,
    "DDOS attack-HOIC": DDOS,
    "DDOS attack-LOIC-UDP": DDOS,
    "DDoS attacks-LOIC-HTTP": DDOS,
    "DoS attacks-GoldenEye": DOS,
    "DoS attacks-Hulk": DOS,
    "DoS attacks-SlowHTTPTest": DOS,
    "DoS attacks-Slowloris": DOS,
    "FTP-BruteForce": BRUTE_FORCE,
    "SSH-Bruteforce": BRUTE_FORCE,
}

# Excluded for scope reasons (Section 6.1). Spelling as in the dataset.
EXCLUDED_LABELS: Final[dict[str, str]] = {
    "Bot": "out of scope: botnet C2 behaviour",
    "Infilteration": "out of scope: multi-stage post-compromise activity",
    "Brute Force -Web": "out of scope: web application attack",
    "Brute Force -XSS": "out of scope: web application attack",
    "SQL Injection": "out of scope: web application attack",
}

ALL_KNOWN_LABELS: Final[frozenset[str]] = frozenset(INCLUDED_LABEL_MAP) | frozenset(EXCLUDED_LABELS)


class UnknownLabelError(ValueError):
    """Raised when the dataset contains Attack labels not listed in Appendix B."""


def map_attack_labels(attack: pd.Series) -> np.ndarray:
    """Map raw ``Attack`` strings to integer project codes.

    Returns an int8 array: the project class code for included labels and
    ``-1`` for excluded *or* unknown labels (callers distinguish the two with
    :func:`label_treatment`).
    """
    mapping = {label: CLASS_TO_CODE[cls] for label, cls in INCLUDED_LABEL_MAP.items()}
    codes = attack.map(mapping)
    return codes.fillna(-1).to_numpy(dtype=np.int8)


def label_treatment(label: str) -> str:
    """Return ``'included'``, ``'excluded'`` or ``'unknown'`` for a raw label."""
    if label in INCLUDED_LABEL_MAP:
        return "included"
    if label in EXCLUDED_LABELS:
        return "excluded"
    return "unknown"


def build_label_mapping_log(
    raw_counts: dict[str, int],
    binary_label_values: dict[str, set[int | str]],
) -> pd.DataFrame:
    """Build the ``label_mapping_log.csv`` table.

    Parameters
    ----------
    raw_counts:
        Count of every distinct raw ``Attack`` value found in the file.
    binary_label_values:
        For each raw ``Attack`` value, the set of distinct values seen in the
        binary ``Label`` column (used to check Label/Attack consistency).
    """
    rows = []
    found = set(raw_counts)
    for label in sorted(found | ALL_KNOWN_LABELS, key=str):
        treatment = label_treatment(label)
        bin_vals = sorted(binary_label_values.get(label, set()), key=str)
        expected_binary = "0" if label == "Benign" else "1"
        consistent = all(str(v) == expected_binary for v in bin_vals) if bin_vals else None
        rows.append(
            {
                "original_label": label,
                "project_class": INCLUDED_LABEL_MAP.get(label, ""),
                "treatment": treatment,
                "reason": EXCLUDED_LABELS.get(label, ""),
                "raw_count": int(raw_counts.get(label, 0)),
                "found_in_file": label in found,
                "listed_in_proposal": label in ALL_KNOWN_LABELS,
                "binary_label_values": ";".join(str(v) for v in bin_vals),
                "binary_label_consistent": consistent,
            }
        )
    return pd.DataFrame(rows)
