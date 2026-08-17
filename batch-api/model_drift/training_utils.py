"""Baseline training-data loader used by psi_report.py for drift detection.

Load order:
  1. A local baseline.csv bundled in this folder. This is the recommended
     path for deployment — it means the deployed service needs zero AWS
     credentials. Generate/refresh it once (locally, with AWS creds handy)
     via `python scripts/export_baseline.py` from the repo root.
  2. Fall back to pulling the same data live from S3, if BASELINE_S3_BUCKET
     (and standard AWS credential env vars) are configured. This keeps the
     original S3-backed workflow available for anyone who prefers it.

Nothing here runs at import time — load_training_data() is only called
lazily, the first time GET /psi is actually hit, so a missing baseline
(or missing AWS credentials) can never crash the service on startup.
"""

import os

import pandas as pd

BASELINE_CSV_PATH = os.path.join(os.path.dirname(__file__), "baseline.csv")


def load_training_data() -> pd.DataFrame:
    if os.path.exists(BASELINE_CSV_PATH):
        return pd.read_csv(BASELINE_CSV_PATH)

    bucket = os.getenv("BASELINE_S3_BUCKET")
    if not bucket:
        raise RuntimeError(
            "No PSI baseline data available: model_drift/baseline.csv is missing "
            "and BASELINE_S3_BUCKET is not set. Either run "
            "`python scripts/export_baseline.py` once to generate baseline.csv "
            "(recommended — removes the AWS dependency entirely), or set "
            "BASELINE_S3_BUCKET plus AWS credentials as env vars to load it "
            "from S3 on each request."
        )

    import boto3

    key = os.getenv("BASELINE_S3_KEY", "raw/sample_credit_risk.csv")
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(obj["Body"], header=0)
