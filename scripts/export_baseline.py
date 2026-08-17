"""One-off helper: export the S3 training-data baseline to a local CSV file
bundled with batch-api, so the deployed service needs zero AWS credentials.

Run this once, locally, wherever you already have AWS credentials configured
(e.g. via `aws configure` or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env
vars). It writes batch-api/model_drift/baseline.csv, which
model_drift/training_utils.py then prefers over calling S3 at all.

Usage:
    pip install boto3 pandas
    python scripts/export_baseline.py
"""

import os

import boto3
import pandas as pd

BUCKET = os.getenv("BASELINE_S3_BUCKET", "newmlopsbucket")
KEY = os.getenv("BASELINE_S3_KEY", "raw/sample_credit_risk.csv")

OUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "batch-api", "model_drift", "baseline.csv"
)


def main() -> None:
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=BUCKET, Key=KEY)
    df = pd.read_csv(obj["Body"], header=0)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()
