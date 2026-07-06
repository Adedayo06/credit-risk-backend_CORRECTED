import boto3
import pandas as pd
from io import StringIO

BUCKET = "newmlopsbucket"
PREFIX = ""

s3 = boto3.client("s3")
def read_csv_from_s3(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(obj["Body"],header=0)

credit_data = read_csv_from_s3(
    BUCKET,f"{PREFIX}raw/sample_credit_risk.csv"
)
def load_training_data():
    return credit_data