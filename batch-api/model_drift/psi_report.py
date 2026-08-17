"""Population Stability Index (PSI) drift report.

Compares the feature distribution of everything scored so far (read straight
out of batch-api's own database) against a fixed training-data baseline
(model_drift/training_utils.py). Lives in batch-api because batch-api is the
service that actually owns the scored-records database — the model-scoring
service (credit-risk-api) stays a pure, stateless scorer with no database or
S3 dependency of its own.

generate_psi_report() takes a SQLAlchemy engine so it works unchanged whether
DATABASE_URL points at local SQLite or a production Postgres instance.
"""

import numpy as np
import pandas as pd

from model_drift.training_utils import load_training_data

FEATURES = [
    "limit_bal",
    "sex",
    "education",
    "marriage",
    "age",
    "pay_0",
    "pay_2",
    "pay_3",
    "pay_4",
    "pay_5",
    "pay_6",
    "bill_amt1",
    "bill_amt2",
    "bill_amt3",
    "bill_amt4",
    "bill_amt5",
    "bill_amt6",
    "pay_amt1",
    "pay_amt2",
    "pay_amt3",
    "pay_amt4",
    "pay_amt5",
    "pay_amt6",
]

# Cached after first load so every /psi request after the first doesn't
# re-read baseline.csv (or re-hit S3) from scratch.
_baseline_cache: pd.DataFrame | None = None


def _get_baseline() -> pd.DataFrame:
    global _baseline_cache
    if _baseline_cache is None:
        _baseline_cache = load_training_data()
    return _baseline_cache


def calculate_psi(expected, actual, bins=10):
    expected = expected.values
    actual = actual.values

    # Calculate percentile breakpoints
    breakpoints = np.percentile(expected, np.arange(0, 101, 100 / bins))

    # Remove duplicate breakpoints
    breakpoints = np.unique(breakpoints)

    # Prevent histogram errors
    if len(breakpoints) < 2:
        return 0

    expected_counts = np.histogram(expected, bins=breakpoints)[0]
    actual_counts = np.histogram(actual, bins=breakpoints)[0]

    expected_perc = expected_counts / len(expected)
    actual_perc = actual_counts / len(actual)

    # Avoid division by zero
    expected_perc = np.where(expected_perc == 0, 0.0001, expected_perc)
    actual_perc = np.where(actual_perc == 0, 0.0001, actual_perc)

    psi = np.sum((actual_perc - expected_perc) * np.log(actual_perc / expected_perc))

    return psi


def generate_psi_report(engine):
    baseline = _get_baseline()

    recent = pd.read_sql(
        f"SELECT {', '.join(FEATURES)} FROM score_report_rows",
        engine,
    )
    recent = recent.dropna()

    if recent.empty:
        return {
            "report": [],
            "overall": (
                "No scored records yet — drift can't be computed until at "
                "least one batch has been scored."
            ),
        }

    report = []
    stable_count = 0
    moderate_count = 0
    significant_count = 0

    for feature in FEATURES:
        psi = calculate_psi(baseline[feature], recent[feature])

        if psi < 0.1:
            status = "Stable"
            stable_count += 1
        elif psi < 0.2:
            status = "Moderate Drift"
            moderate_count += 1
        else:
            status = "Significant Drift"
            significant_count += 1

        report.append({
            "feature": feature,
            "psi": round(float(psi), 3),
            "status": status,
        })

    if significant_count > 0:
        overall = (
            f"Significant drift detected in {significant_count} feature(s). "
            "Model retraining is recommended."
        )
    elif moderate_count > 0:
        overall = (
            f"Moderate drift detected in {moderate_count} feature(s). "
            "Continue monitoring the model."
        )
    else:
        overall = "No significant drift detected. The model remains stable."

    return {
        "report": report,
        "overall": overall,
    }
