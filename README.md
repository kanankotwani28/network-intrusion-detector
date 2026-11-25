# Consistency-Preserving Adversarial Robustness and SHAP-Guided Hybrid Defence for Flow-Based NIDS

B.Tech. (CSE), 5th Semester — CS24300 Minor Project, BIT Mesra (Patna Campus).
Guide: Dr. Subhash Chandra Pandey.

## 1. Objective

This project builds a flow-based Network Intrusion Detection System (NIDS)
on the standardized **NF-CSE-CIC-IDS2018-v2** NetFlow benchmark, and asks a
narrower question than "how accurate is the classifier?": **does the
classifier's accuracy depend on traffic *timing* in a way an attacker can
exploit without changing what the attack actually does?**

An attacker running a DoS/DDoS flood or an SSH/FTP brute-force can *pace*
their traffic — stretch out the flow duration, send fewer bytes per second —
while keeping every other property of the attack (which port, how many
bytes total, the TCP flags, the packet-size distribution) unchanged. If a
detector leans on duration- and rate-derived features, this pacing can
evade it for free. This project measures that fragility, tries three ways
to fix it, and uses SHAP (not just as a ranking table, but as a design and
audit tool) to show *why* each fix does or doesn't work.

## 2. Research questions

| # | Question |
|---|---|
| RQ1 | How much does a standard LightGBM baseline (M1) rely on timing/throughput features, and how much of its detected attack traffic evades when flow timing is stretched? |
| RQ2 | Does simply deleting all timing features (M2) solve evasion, or does it degrade clean detection F1? |
| RQ3 | Does unguided Gaussian noise (M3) match structured, domain-aware hardening? |
| RQ4 | Does the SHAP-guided two-layer hybrid defence (M5) recover the clean accuracy lost in M2 while improving out-of-distribution robustness over adversarial hardening alone (M4)? |
| RQ5 | Do adversarial hardening (M4) and hybrid feature engineering (M5) shift predictive weight off fragile timing features and onto invariant structural ones? |

This is an empirically honest study: a high or low evasion rate, a
successful or failed hybrid defence, are *all* valid results. Nothing here
assumes M5 wins.

## 3. Dataset and class scope

**Source:** `NF-CSE-CIC-IDS2018-v2` (Sarhan et al.), a standardized NetFlow
v9 re-export of the AWS-hosted CSE-CIC-IDS2018 testbed: ~18.9M flows, 43
published features, plus `Label` (binary) and `Attack` (15 original class
names).

Four project classes are used, matched by **exact** label string (never a
substring match, to avoid confusing e.g. `"Brute Force -Web"` with
`"FTP-BruteForce"`):

| Project class | Original `Attack` labels |
|---|---|
| Benign | `Benign` |
| DDoS | `DDOS attack-HOIC`, `DDOS attack-LOIC-UDP`, `DDoS attacks-LOIC-HTTP` |
| DoS | `DoS attacks-GoldenEye`, `DoS attacks-Hulk`, `DoS attacks-SlowHTTPTest`, `DoS attacks-Slowloris` |
| Brute-Force | `FTP-BruteForce`, `SSH-Bruteforce` |

`Bot`, `Infilteration` (sic), and the three web-application-attack labels
(`Brute Force -Web`, `Brute Force -XSS`, `SQL Injection`) are **excluded by
design**, not because they are rare: they are not timing-pacing-sensitive
attacks (see the proposal, Section 6.1, for the full rationale). Any label
found in the file that isn't one of these 15 halts the pipeline instead of
being silently guessed at (`nids.data.label_mapping`).

`Label` and `Attack` are never model inputs. `IPV4_SRC_ADDR`,
`IPV4_DST_ADDR` and `L4_SRC_PORT` are dropped as identifiers (to stop trees
memorising fixed testbed IPs/ephemeral ports); `L4_DST_PORT` is kept. That
leaves **40 model-input features**: 33 structural (`NT`, invariant under
pacing) + 7 timing/rate (`TM`, duration and byte-rate/throughput columns).
The full column-by-column schema is `src/nids/features/feature_groups.py`,
the single source of truth every other module imports from.

## 4. System architecture

```
src/nids/
  config/        Pydantic-validated experiment.yaml loader
  data/          ingestion, label mapping, validation, dedup, sampling, split, schema, data identities
  features/      canonical feature-group lists; (ratios.py added in Phase 4)
  utils/         logging, reproducibility (run_config.json), small IO helpers
tests/           pytest suite, synthetic data only (no 18.9M-row file needed)
configs/         configs/experiment.yaml — every tunable in one place
scripts/         run_pipeline.py (Phase 1); more added per phase
data/            raw/ (you place the CSV here) · interim/ · processed/ (parquet; gitignored)
artifacts/       models, metrics, plots, reports, run_config.json (gitignored)
```

Fixed pipeline order (never reordered, and enforced by the call sequence in
`scripts/run_pipeline.py`):

```
Filter -> Validate -> Deduplicate -> Stratified sample -> Train/test split -> Model-specific transformations
```

The 70/30 split happens **once**, before any feature engineering, scaling,
SHAP selection or adversarial augmentation, and is reused by every model and
every seed — this is what makes cross-model comparisons fair and leak-free.

### Memory-safe two-pass ingestion

The 18.9M-row file is never loaded into memory. **Pass 1** streams the CSV
in `chunksize=200_000`-row chunks, filters to the 4 project classes,
validates (finite, non-negative), drops identifiers, and for every valid
row computes a 64-bit hash of `(40 model features, project label)` — only
that hash, the class, and the row's position in the file are kept (a few
bytes per row, not the row itself). Deduplication and the largest-remainder
sampling quotas are computed purely from those compact hash tables. **Pass
2** re-streams the file and extracts only the globally-selected rows, which
are then written to `data/processed/sample_100k.parquet`.

## 5. Why these specific engineering decisions

- **Hashing is vectorised** (`pandas.util.hash_pandas_object` over a
  byte-view of the feature matrix) rather than hashed row-by-row in a
  Python loop — the latter would take hours over millions of eligible rows.
  A 64-bit hash collision between two genuinely different flows is
  astronomically unlikely at this scale (birthday bound ≈ n²/2⁶⁵, far below
  1 for a few million rows); this is documented as an accepted limitation
  rather than solved by holding every raw row in memory (which would defeat
  the whole point of two-pass ingestion). `verify_hash_collisions()` is
  provided for anyone who wants to confirm a specific suspected collision.
- **Conflicting duplicate labels are never silently dropped.** If the same
  feature vector appears with two different project labels, one copy of
  *each* distinct (features, label) pair is kept and the conflict is logged
  to `duplicate_conflicts.csv`; if conflicts exceed 1% of unique rows the
  pipeline halts instead of quietly proceeding (configurable).
- **Rate/throughput scaling under the perturbation engine is verified
  empirically, not assumed.** `nids.data.identities.IdentityAccumulator`
  tests several candidate relations (which byte column, which duration
  column, bytes/s vs. bits/s) on the clean data and only approves a column
  for `1/alpha` scaling if the best proportional candidate holds within 5%
  relative error for ≥95% of positive-duration flows. The same accumulator
  determines empirically whether the five packet-size bins sum to
  `IN_PKTS` or `IN_PKTS + OUT_PKTS`, which fixes the denominator of the
  engineered packet-size-share ratios used later in M5.
- **Pydantic-validated config** (`configs/experiment.yaml` ->
  `nids.config.settings.load_settings`) rejects invalid combinations at
  load time — e.g. `class_weight != 'balanced'`, or an alpha range that
  isn't increasing — rather than letting a typo silently change an
  experiment.

## 6. Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Exact versions actually installed in this environment are pinned in
`requirements.lock.txt` and are also recorded (with the executing Python
and platform) in `artifacts/run_config.json` every time a phase script
runs.

## 7. Dataset setup (required before Phase 1 can run on real data)

Download `NF-CSE-CIC-IDS2018-v2` from the official UQ dataset page
(University of Queensland, Sarhan et al. — see the proposal's References,
item 3) and place the CSV at the path given by `paths.raw_dataset` in
`configs/experiment.yaml` (default: `data/raw/NF-CSE-CIC-IDS2018-v2.csv`),
or edit that path to point at your copy. Expected format: a header row
matching the 43 published NetFlow v9 columns plus `Label` and `Attack` (45
columns total) — `scripts/run_pipeline.py` checks this automatically and
reports any discrepancy to `artifacts/data/schema_verification.csv` rather
than silently renaming or substituting columns.

> **This session's container has no network access to the UQ dataset host
> or other external mirrors**, so the real file could not be downloaded
> here. Phase 1's code is fully implemented and its unit/integration tests
> pass against small synthetic NetFlow-shaped data — see §9 "Current status"
> — but it has not yet been run against the genuine 18.9M-row file. Once you
> provide the CSV (or a reachable path/URL to it), Phase 1 can be executed
> for real and Phases 2–6 can follow.

## 8. Running things

```bash
# Phase 1: ingest, validate, dedup, sample, split (needs the raw CSV, see §7)
python scripts/run_pipeline.py --config configs/experiment.yaml

# Tests (synthetic data only, no raw CSV needed)
pytest
```

## 9. Current status (updated as phases complete)

- [x] **Phase 0 — Repository audit.** Empty repository (no commits), clean
      Python 3.13 environment with no project dependencies pre-installed.
      Proposal PDF read in full; this README and the architecture above
      follow it directly. A project virtualenv was created and
      `lightgbm`, `shap`, `scikit-learn`, `pandas`, `numpy`, `pyarrow`,
      `matplotlib`, `pydantic`, `pyyaml`, `tqdm`, `pytest` installed and
      pinned (`requirements.lock.txt`).
- [x] **Phase 1 — Data pipeline (code + tests).** Schema verification,
      exact label mapping, chunked two-pass ingestion, row validation,
      hash-based deduplication (with conflict reporting), empirical
      rate/duration identity checks, largest-remainder sampling, and the
      single stratified 70/30 split are all implemented
      (`src/nids/data/`, `src/nids/features/`, `src/nids/config/`).
      **41 pytest tests pass** against synthetic data (`tests/`), including
      a full end-to-end pipeline test and an unknown-label-halts test.
      The pipeline script (`scripts/run_pipeline.py`) was additionally
      smoke-tested on a larger synthetic CSV and correctly: excluded
      `Bot`/`Infilteration`, deduplicated, computed exact largest-remainder
      quotas, and produced a reproducible stratified split.
      **Blocked on real data** — see §7.
- [ ] Phase 2 — M1 baseline / M2 no-timing ablation.
- [ ] Phase 3 — Consistency-preserving perturbation engine.
- [ ] Phase 4 — M3 noise / M4 adversarial / M5 SHAP-guided hybrid.
- [ ] Phase 5 — Five-seed evaluation, AER, SHAP drift audit.
- [ ] Phase 6 — Final report.

## 10. Limitations (carried from the proposal, Section 12)

1. Stretching duration 3×–4.5× reduces instantaneous packet rate, so the
   evaluation is bounded to pacing regimes where connection-table
   exhaustion and credential brute-forcing remain viable attacks.
2. The perturbation is algebraic (flow-level), not a full packet-level TCP
   stack replay — retransmission counters and TCP window fields are held
   fixed by design.
3. `CSE-CIC-IDS2018` reflects an AWS enterprise testbed, not raw ISP
   backbone traffic; experiments are scoped to LightGBM ensembles on
   zero-cost CPU compute.
4. The NetFlow v9 schema used here has no capture-day or session
   identifier, so a grouped/time-based split is not possible; the random
   stratified split may place similar flows from the same capture period in
   both train and test. Exact-duplicate deduplication reduces this effect
   but does not remove it.
5. `Bot`, `Infiltration` and web attacks are out of scope by design;
   conclusions do not extend to them. Brute-Force has few test flows, so
   its class-specific metrics are always reported with sample counts and
   flagged as low-support below 200.
6. Reported standard deviations are over 5 seeds on one fixed sample and
   split; they do not capture variability from re-sampling or re-splitting
   the data.

## 11. Reproducibility

Seeds: `[42, 101, 202, 303, 404]` (model training / augmentation / test
perturbation draws). Sampling and the train/test split use a separate fixed
seed (`42`), drawn once and reused everywhere. Every phase script appends
its actual parameters, software versions, dataset checksum, and completion
timestamp to `artifacts/run_config.json` — this file reflects what was
really executed, never a plan.
