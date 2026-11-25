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
  config/           Pydantic-validated experiment.yaml loader
  data/             ingestion, label mapping, validation, dedup, sampling, split, schema, data identities
  features/         canonical feature-group lists, engineered timing-invariant ratios
  perturbation/      consistency-preserving pacing engine + its 9-invariant verifier
  models/           shared LightGBM wrapper, M3/M4 augmentation, M5 SHAP selection
  evaluation/       metrics, attack-evasion-rate, 5-seed mean+/-std aggregation
  explainability/   non-circular SHAP attribution-drift audit
  utils/            logging, reproducibility (run_config.json), small IO helpers
tests/              pytest suite, synthetic data only (no 18.9M-row file needed)
configs/            experiment.yaml -- every tunable in one place
scripts/            run_pipeline.py / run_phase{2,3,4,5}.py / generate_report.py
data/               raw/ (dataset here) . interim/ . processed/ (parquet; gitignored)
artifacts/          models, metrics, plots, reports, run_config.json (gitignored)
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

## 7. Dataset provenance

The official UQ dataset host was not reachable from this container. Instead
the dataset was downloaded from the Kaggle mirror
[`dhoogla/nfcsecicids2018v2`](https://www.kaggle.com/datasets/dhoogla/nfcsecicids2018v2)
on 2026-11-25, as a single Parquet file (SHA-256 of
`NF-CSE-CIC-IDS2018-V2.parquet`:
`f299c8a2cb1223912438aae68f3818f898c97ce1824b2deef618f56f266562cb`, also
recorded in `artifacts/run_config.json` on every pipeline run). This is
verified to be the same underlying dataset, not a different one:

- **All 43 published NetFlow v9 feature names match Appendix A exactly**
  (cross-checked programmatically against `src/nids/features/feature_groups.py`).
- **All 15 original `Attack` label strings match Appendix B exactly**,
  including the dataset's own misspelling `"Infilteration"`, with fully
  consistent binary `Label` values (0 for Benign, 1 for every attack label,
  with zero exceptions across the full 17.1M rows).

Two differences from the proposal's assumptions, found empirically and
reported rather than silently absorbed:

1. **`IPV4_SRC_ADDR` and `IPV4_DST_ADDR` are absent** from this mirror
   (privacy-stripped upstream). This is harmless for the project — both are
   dropped as identifiers anyway — and is handled automatically (`nids.data.schema`
   treats a missing identifier column as non-fatal; `L4_SRC_PORT`, the third
   identifier, *is* present and is dropped as usual).
2. **Row count is 17,129,715, not 18,893,708** (the proposal's Table 6
   figure, from Sarhan et al., pre-deduplication). Per-class, `DoS`
   (483,999) and `Brute-Force` (120,912) match the proposal's figures
   *exactly*; only `Benign` and `DDoS` are lower. This is consistent with
   this mirror having had exact-duplicate flows removed upstream — a known,
   well-documented property of CIC-IDS2018-derived NetFlow re-exports,
   where DDoS/Benign floods produce enormous numbers of near-identical
   flows. The project's own deduplication step (Section 7.3) runs
   regardless and independently confirms this: it found **zero**
   additional conflicting-label duplicate groups in this already-cleaned
   copy.

If you obtain the original UQ CSV instead, point `paths.raw_dataset` at it
in `configs/experiment.yaml` — the pipeline reads either CSV or Parquet
automatically by file extension — and these two notes would no longer
apply (though the dedup step would then likely remove far more rows, as
anticipated by the proposal).

## 7a. Two real data-quality findings from Phase 1 (empirical, not assumed)

Running the empirical rate/duration identity checks (Appendix C) against
the full real dataset surfaced two genuine findings that materially affect
later phases. Both are handled exactly as the proposal's own fallback
rules prescribe (Appendix C: *"If a column fails verification: hold it at
its original value, report the failure, document the limitation — do not
drop it from M1"*), not worked around:

**(1) `FLOW_DURATION_MILLISECONDS` is corrupted for almost the entire
dataset.** 86.1% of valid flows have this field equal to exactly `0`, and
of the remainder, 99.1% cluster tightly around 4,294,9xx ms — i.e. almost
exactly 2³² *microseconds* (≈4,294,967.296 ms). This is a well-documented
32-bit counter overflow in the nProbe NetFlow exporter used to build this
dataset, not a bug in this pipeline (independently re-verified directly
against the raw Parquet, bypassing this project's code entirely).
`DURATION_IN` and `DURATION_OUT` do **not** show this pattern (sane
distributions up to ~107 seconds) and are the usable duration signals.
`validation_drops.csv` reports the three duration columns' zero/wrap flags
separately rather than one combined flag, specifically so this asymmetry
is visible rather than hidden.

**(2) None of the four rate/throughput columns satisfy the proposal's
scaling-eligibility criterion.** `SRC_TO_DST_SECOND_BYTES`,
`DST_TO_SRC_SECOND_BYTES`, `SRC_TO_DST_AVG_THROUGHPUT` and
`DST_TO_SRC_AVG_THROUGHPUT` were each tested against every candidate
`bytes / duration` relationship (both duration columns, both unit
conventions); the best candidate for each column held within 5% relative
error for at most 29.4% of positive-duration flows — far short of the 95%
acceptance bar (full table: `artifacts/data/rate_identity_checks.csv`).
Binned analysis shows the mismatch is *not* only the duration-corruption
issue above (it persists even restricted to flows with sane `DURATION_OUT`
values), so it reflects an independent quantization/rounding
characteristic of how this exporter computes these four fields.
**Consequence for Phase 3:** per Appendix C's documented fallback, all four
rate/throughput columns will be held **fixed** (unperturbed) rather than
scaled by `1/alpha` in the pacing perturbation engine — the same treatment
as the fixed structural features. This is reported as a limitation of the
dataset's export tooling, not of the perturbation design, and is exactly
the kind of outcome the proposal's Empirical Honesty Protocol (Section 3)
anticipates: it is reported plainly rather than assumed away.

A third, purely mechanical finding: the five `NUM_PKTS_*` packet-size bins
sum to `IN_PKTS + OUT_PKTS` (93.5% exact match) rather than `IN_PKTS`
alone, so the M5 engineered `SHARE_*` ratios (Phase 4) will use
`max(IN_PKTS + OUT_PKTS, 1)` as their denominator, per Appendix D's
contingency rule.

## 8. Running things

```bash
# Phase 1: ingest, validate, dedup, sample, split
python scripts/run_pipeline.py --config configs/experiment.yaml

# Phase 2: M1 baseline, M2 ablation, M1 feature importance, M5 SHAP selection (frozen)
python scripts/run_phase2.py --config configs/experiment.yaml

# Phase 3: perturbation engine across all 5 seeds + consistency verification
python scripts/run_phase3.py --config configs/experiment.yaml

# Phase 4: train M3 (noise), M4 (adversarial), M5 (hybrid) at seed 42, verify acceptance criteria
python scripts/run_phase4.py --config configs/experiment.yaml

# Phase 5: full 5-seed evaluation of all 5 models + non-circular SHAP drift audit
python scripts/run_phase5.py --config configs/experiment.yaml

# Phase 6: assemble results_summary.md from the artifacts above
python scripts/generate_report.py

# Tests (synthetic data only, no raw dataset needed) -- 94 tests
pytest
```

Each script is idempotent and reads/writes `artifacts/run_config.json`
incrementally, so phases can be re-run independently once their inputs
exist. See `artifacts/reports/results_summary.md` for the full results
after running Phases 1-6.

## 9. Current status (updated as phases complete)

- [x] **Phase 0 — Repository audit.** Empty repository (no commits), clean
      Python 3.13 environment with no project dependencies pre-installed.
      Proposal PDF read in full; this README and the architecture above
      follow it directly. A project virtualenv was created and
      `lightgbm`, `shap`, `scikit-learn`, `pandas`, `numpy`, `pyarrow`,
      `matplotlib`, `pydantic`, `pyyaml`, `tqdm`, `pytest` installed and
      pinned (`requirements.lock.txt`).
- [x] **Phase 1 — Data pipeline. Run on the real dataset.** Schema
      verification, exact label mapping, chunked two-pass ingestion (now
      supporting both CSV and Parquet), row validation, hash-based
      deduplication (with conflict reporting), empirical rate/duration
      identity checks, largest-remainder sampling, and the single
      stratified 70/30 split are all implemented
      (`src/nids/data/`, `src/nids/features/`, `src/nids/config/`).
      **43 pytest tests pass** against synthetic data (`tests/`).
      `scripts/run_pipeline.py` was then run on the real 17,129,715-row
      `NF-CSE-CIC-IDS2018-v2` file (see §7 for provenance) and produced
      every Appendix G data-stage artifact under `artifacts/data/` and
      `data/processed/`:
      - 16,982,667 rows eligible across the 4 project classes; **zero**
        validation drops (NaN/Inf/negative) across the whole file; **zero**
        unknown Attack labels; **zero** conflicting-label duplicate groups.
      - Unique eligible rows per class after deduplication: Benign
        8,488,924 · DDoS 114,638 · DoS 338,755 · Brute-Force 14,720.
      - 100,000-flow sample drawn via largest-remainder quotas (Benign
        94,774 · DDoS 1,280 · DoS 3,782 · Brute-Force 164), split 70/30 ->
        train 70,000 / test 30,000 rows, test set has only 49 Brute-Force
        flows (**flagged low-support**, as the proposal itself anticipated).
      - Two genuine, proposal-relevant data-quality findings (§7a):
        `FLOW_DURATION_MILLISECONDS` is corrupted for ~100% of flows (a
        known nProbe 32-bit counter overflow), and none of the four
        rate/throughput columns pass the Appendix C scaling-eligibility
        check — both are handled per the proposal's own documented
        fallback (hold the column fixed, report the failure), not patched
        around.
- [x] **Phase 2 — M1/M2 + M5 SHAP selection.** M1 and M2 trained on the
      real split; identical clean performance (macro-F1 0.9974 for both),
      confirming structural features alone fully separate the 4 classes
      here. SHAP flagged `FLOW_DURATION_MILLISECONDS` and `DURATION_IN` as
      fragile (>=2.5% importance share); M5's 46-feature layer frozen to
      `artifacts/data/m5_feature_list.json`.
- [x] **Phase 3 — Perturbation engine, 5 seeds.** All 450 consistency
      checks (45 invariants x 5 seeds x 2 regimes) pass. **AER = 0.00%**
      for M1 and M2, every class, every seed, both moderate and OOD
      regimes — see §7a and the Results Summary for why.
- [x] **Phase 4 — M3/M4/M5 trained and verified.** Augmentation pool
      sizes exact, M5 uses the frozen feature list, all three share
      M1/M2's hyperparameters and split. Clean macro-F1 0.9999 for all
      three. (Found and fixed along the way: a pathological outlier in
      `SRC_TO_DST_SECOND_BYTES` overflows naive `std()` to `inf`, now
      guarded in the Gaussian-noise augmenter.)
- [x] **Phase 5 — Full 5-seed evaluation + SHAP drift audit.** All 5
      models retrained per seed; clean/moderate/OOD metrics, AER by
      class, mean+/-std aggregation, confusion matrices and comparison
      plots all written from real runs. **AER stays 0.00% for every
      model** (M3/M4/M5 had nothing to recover from). The non-circular
      SHAP audit (M1 vs M4 vs M5, ground-truth class, OOD, seed 42) is
      the project's most interesting positive finding: M1 attributes
      16.8% of its prediction weight to fragile timing/rate features on
      clean data; M4 only 3.8%; M5's remaining unflagged timing features
      only 2.7% (plus 30.7% routed onto the engineered invariant ratios).
      Adversarial hardening and hybrid feature engineering measurably
      shift predictive weight off timing features, independent of
      whether the specific evasion attack succeeds on this dataset.
- [x] **Phase 6 — Final report.** `scripts/generate_report.py` assembles
      `artifacts/reports/results_summary.md` answering all 5 research
      questions directly from the artifact files (no fabricated numbers).

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
