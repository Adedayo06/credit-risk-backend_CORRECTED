import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import sqlite3
import numpy as np

from model_drift.training_utils import load_training_data

# Load original training data once when the application starts
baseline = load_training_data()

# Database location
BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "batch-api"
    )
)

DB_PATH = os.path.join(
    BASE_DIR,
    "credit_risk_scores.db"
)

if not os.path.exists(DB_PATH):
    raise FileNotFoundError(
        f"Database not found: {DB_PATH}"
    )


def calculate_psi(expected, actual, bins=10):

    expected = expected.values
    actual = actual.values

    # Calculate percentile breakpoints
    breakpoints = np.percentile(
        expected,
        np.arange(0, 101, 100 / bins)
    )

    # Remove duplicate breakpoints
    breakpoints = np.unique(breakpoints)

    # Prevent histogram errors
    if len(breakpoints) < 2:
        return 0

    expected_counts = np.histogram(
        expected,
        bins=breakpoints
    )[0]

    actual_counts = np.histogram(
        actual,
        bins=breakpoints
    )[0]

    expected_perc = expected_counts / len(expected)
    actual_perc = actual_counts / len(actual)

    # Avoid division by zero
    expected_perc = np.where(expected_perc == 0, 0.0001, expected_perc)
    actual_perc = np.where(actual_perc == 0, 0.0001, actual_perc)

    psi = np.sum(
        (actual_perc - expected_perc)
        * np.log(actual_perc / expected_perc)
    )

    return psi


features = [
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
    "pay_amt6"
]


def generate_psi_report():

    # Open a fresh SQLite connection for this request
    with sqlite3.connect(DB_PATH) as conn:

        recent = pd.read_sql("""
        SELECT
            limit_bal,
            sex,
            education,
            marriage,
            age,
            pay_0,
            pay_2,
            pay_3,
            pay_4,
            pay_5,
            pay_6,
            bill_amt1,
            bill_amt2,
            bill_amt3,
            bill_amt4,
            bill_amt5,
            bill_amt6,
            pay_amt1,
            pay_amt2,
            pay_amt3,
            pay_amt4,
            pay_amt5,
            pay_amt6
        FROM score_report_rows
        """, conn)

    # Remove missing values
    recent = recent.dropna()

    report = []

    stable_count = 0
    moderate_count = 0
    significant_count = 0

    for feature in features:

        psi = calculate_psi(
            baseline[feature],
            recent[feature]
        )

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
            "status": status
        })
      

    # Generate overall recommendation
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
        overall = (
            "No significant drift detected. "
            "The model remains stable."
        )

    return {
        "report": report,
        "overall": overall
    }