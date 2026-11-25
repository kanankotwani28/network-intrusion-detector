"""Canonical feature definitions (proposal Appendix A and Appendix D).

This module is the single source of truth for every column list used by the
project. Every other module imports its feature lists from here, so a column
cannot silently drift between ingestion, training, perturbation and audit.

Counts (validated by ``tests/test_schema.py``):
    43 published features = 3 identifiers + 40 model-input features
    40 model-input features = 33 structural (NT) + 7 timing/rate (TM)
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Identifiers: dropped from every model (prevents memorising testbed IPs and
# ephemeral client ports). L4_DST_PORT is deliberately NOT an identifier.
# --------------------------------------------------------------------------
IDENTIFIER_FEATURES: Final[list[str]] = [
    "IPV4_SRC_ADDR",
    "IPV4_DST_ADDR",
    "L4_SRC_PORT",
]

# --------------------------------------------------------------------------
# Timing / rate features (TM). Duration columns scale by alpha, rate columns
# by 1/alpha under the pacing perturbation (Appendix C).
# --------------------------------------------------------------------------
DURATION_FEATURES: Final[list[str]] = [
    "FLOW_DURATION_MILLISECONDS",
    "DURATION_IN",
    "DURATION_OUT",
]

RATE_FEATURES: Final[list[str]] = [
    "SRC_TO_DST_SECOND_BYTES",
    "DST_TO_SRC_SECOND_BYTES",
    "SRC_TO_DST_AVG_THROUGHPUT",
    "DST_TO_SRC_AVG_THROUGHPUT",
]

TIMING_FEATURES: Final[list[str]] = DURATION_FEATURES + RATE_FEATURES

# --------------------------------------------------------------------------
# Structural features (NT), in Appendix D order. Invariant under pacing.
# --------------------------------------------------------------------------
STRUCTURAL_FEATURES: Final[list[str]] = [
    "L4_DST_PORT",
    "PROTOCOL",
    "L7_PROTO",
    "IN_BYTES",
    "OUT_BYTES",
    "IN_PKTS",
    "OUT_PKTS",
    "TCP_FLAGS",
    "CLIENT_TCP_FLAGS",
    "SERVER_TCP_FLAGS",
    "MIN_TTL",
    "MAX_TTL",
    "LONGEST_FLOW_PKT",
    "SHORTEST_FLOW_PKT",
    "MIN_IP_PKT_LEN",
    "MAX_IP_PKT_LEN",
    "RETRANSMITTED_IN_BYTES",
    "RETRANSMITTED_IN_PKTS",
    "RETRANSMITTED_OUT_BYTES",
    "RETRANSMITTED_OUT_PKTS",
    "NUM_PKTS_UP_TO_128_BYTES",
    "NUM_PKTS_128_TO_256_BYTES",
    "NUM_PKTS_256_TO_512_BYTES",
    "NUM_PKTS_512_TO_1024_BYTES",
    "NUM_PKTS_1024_TO_1514_BYTES",
    "TCP_WIN_MAX_IN",
    "TCP_WIN_MAX_OUT",
    "ICMP_TYPE",
    "ICMP_IPV4_TYPE",
    "DNS_QUERY_ID",
    "DNS_QUERY_TYPE",
    "DNS_TTL_ANSWER",
    "FTP_COMMAND_RET_CODE",
]

PACKET_SIZE_BIN_FEATURES: Final[list[str]] = [
    "NUM_PKTS_UP_TO_128_BYTES",
    "NUM_PKTS_128_TO_256_BYTES",
    "NUM_PKTS_256_TO_512_BYTES",
    "NUM_PKTS_512_TO_1024_BYTES",
    "NUM_PKTS_1024_TO_1514_BYTES",
]

# The 40 model-input features used by M1, M3 and M4 (NT + TM).
MODEL_FEATURES: Final[list[str]] = STRUCTURAL_FEATURES + TIMING_FEATURES

# --------------------------------------------------------------------------
# Published schema: all 43 features in Appendix A order, plus the targets.
# --------------------------------------------------------------------------
PUBLISHED_FEATURE_ORDER: Final[list[str]] = [
    "IPV4_SRC_ADDR",
    "IPV4_DST_ADDR",
    "L4_SRC_PORT",
    "L4_DST_PORT",
    "PROTOCOL",
    "L7_PROTO",
    "IN_BYTES",
    "OUT_BYTES",
    "IN_PKTS",
    "OUT_PKTS",
    "FLOW_DURATION_MILLISECONDS",
    "TCP_FLAGS",
    "CLIENT_TCP_FLAGS",
    "SERVER_TCP_FLAGS",
    "DURATION_IN",
    "DURATION_OUT",
    "MIN_TTL",
    "MAX_TTL",
    "LONGEST_FLOW_PKT",
    "SHORTEST_FLOW_PKT",
    "MIN_IP_PKT_LEN",
    "MAX_IP_PKT_LEN",
    "SRC_TO_DST_SECOND_BYTES",
    "DST_TO_SRC_SECOND_BYTES",
    "RETRANSMITTED_IN_BYTES",
    "RETRANSMITTED_IN_PKTS",
    "RETRANSMITTED_OUT_BYTES",
    "RETRANSMITTED_OUT_PKTS",
    "SRC_TO_DST_AVG_THROUGHPUT",
    "DST_TO_SRC_AVG_THROUGHPUT",
    "NUM_PKTS_UP_TO_128_BYTES",
    "NUM_PKTS_128_TO_256_BYTES",
    "NUM_PKTS_256_TO_512_BYTES",
    "NUM_PKTS_512_TO_1024_BYTES",
    "NUM_PKTS_1024_TO_1514_BYTES",
    "TCP_WIN_MAX_IN",
    "TCP_WIN_MAX_OUT",
    "ICMP_TYPE",
    "ICMP_IPV4_TYPE",
    "DNS_QUERY_ID",
    "DNS_QUERY_TYPE",
    "DNS_TTL_ANSWER",
    "FTP_COMMAND_RET_CODE",
]

LABEL_COLUMN: Final[str] = "Label"
ATTACK_COLUMN: Final[str] = "Attack"
TARGET_COLUMNS: Final[list[str]] = [LABEL_COLUMN, ATTACK_COLUMN]

PUBLISHED_COLUMNS: Final[list[str]] = PUBLISHED_FEATURE_ORDER + TARGET_COLUMNS

# Columns that rates/throughputs should be expressed in (floats); everything
# else in the model set is an integer count/code in the published schema.
FLOAT_FEATURES: Final[list[str]] = list(RATE_FEATURES)
INTEGER_FEATURES: Final[list[str]] = [c for c in MODEL_FEATURES if c not in FLOAT_FEATURES]

# --------------------------------------------------------------------------
# M3 Gaussian-noise features: Appendix A "Noise = Y" column. Continuous
# quantities only; ports, protocols, flags, TTLs, ICMP/DNS/FTP codes excluded.
# --------------------------------------------------------------------------
NOISE_FEATURES: Final[list[str]] = [
    "IN_BYTES",
    "OUT_BYTES",
    "IN_PKTS",
    "OUT_PKTS",
    "FLOW_DURATION_MILLISECONDS",
    "DURATION_IN",
    "DURATION_OUT",
    "LONGEST_FLOW_PKT",
    "SHORTEST_FLOW_PKT",
    "MIN_IP_PKT_LEN",
    "MAX_IP_PKT_LEN",
    "SRC_TO_DST_SECOND_BYTES",
    "DST_TO_SRC_SECOND_BYTES",
    "RETRANSMITTED_IN_BYTES",
    "RETRANSMITTED_IN_PKTS",
    "RETRANSMITTED_OUT_BYTES",
    "RETRANSMITTED_OUT_PKTS",
    "SRC_TO_DST_AVG_THROUGHPUT",
    "DST_TO_SRC_AVG_THROUGHPUT",
    "NUM_PKTS_UP_TO_128_BYTES",
    "NUM_PKTS_128_TO_256_BYTES",
    "NUM_PKTS_256_TO_512_BYTES",
    "NUM_PKTS_512_TO_1024_BYTES",
    "NUM_PKTS_1024_TO_1514_BYTES",
    "TCP_WIN_MAX_IN",
    "TCP_WIN_MAX_OUT",
]

DISCRETE_FEATURES: Final[list[str]] = [c for c in MODEL_FEATURES if c not in NOISE_FEATURES]

# --------------------------------------------------------------------------
# Engineered timing-invariant ratios (M5 only; Appendix D "EN").
# --------------------------------------------------------------------------
ENGINEERED_FEATURES: Final[list[str]] = [
    "BPP_IN",
    "BPP_OUT",
    "DIR_RATIO",
    "SHARE_128",
    "SHARE_128_256",
    "SHARE_256_512",
    "SHARE_512_1024",
    "SHARE_1024_1514",
]


def assert_no_target_columns(columns: list[str]) -> None:
    """Raise if a target or identifier column appears in a model feature list.

    Called by every model-building function as a leakage guard.
    """
    forbidden = set(TARGET_COLUMNS) | set(IDENTIFIER_FEATURES) | {"y", "project_class", "flow_id"}
    leaked = sorted(forbidden.intersection(columns))
    if leaked:
        raise ValueError(f"Forbidden columns in model feature list: {leaked}")
