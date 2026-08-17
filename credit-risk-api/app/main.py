from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import pandas as pd
import json
import os

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

# credit-risk-api is a pure, stateless model-scoring service: no database,
# no S3, no dependency on any other service. Drift/PSI reporting lives in
# batch-api instead, since that's the service that actually owns the scored
# records the drift comparison needs (see batch-api/model_drift/).
app = FastAPI()

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = joblib.load("model/credit_risk_model.joblib")


class CreditApplication(BaseModel):
    id: int
    limit_bal: int
    sex: int
    education: int
    marriage: int
    age: int

    pay_0: int
    pay_2: int
    pay_3: int
    pay_4: int
    pay_5: int
    pay_6: int

    bill_amt1: float
    bill_amt2: float
    bill_amt3: float
    bill_amt4: float
    bill_amt5: float
    bill_amt6: float

    pay_amt1: float
    pay_amt2: float
    pay_amt3: float
    pay_amt4: float
    pay_amt5: float
    pay_amt6: float

@app.get("/")
def root():
    return {"message": "Credit Risk API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/metrics")
def metrics():
    """Return the trained model's evaluation metrics (from metrics.json)."""
    path = os.path.join(MODEL_DIR, "metrics.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="metrics.json not found")



@app.post("/score")
def score(application: CreditApplication):

    df = pd.DataFrame([application.dict()])

    prediction = int(model.predict(df)[0])

    probability = float(model.predict_proba(df)[0][1])

    if probability >= 0.35:
        risk_band = "High risk of default"
        recommendation = "Decline"
    elif probability >= 0.10:
        risk_band = "Medium risk of default"
        recommendation = "Send for manual review"
    else:
        risk_band = "Low risk of default"
        recommendation = "Approve"

    return {
        "default_prediction": prediction,
        "probability_of_default": round(probability, 4),
        "risk_band": risk_band,
        "recommendation": recommendation
    }