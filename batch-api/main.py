import csv
import os
import uuid
from datetime import datetime, timezone
from io import StringIO
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from model_drift.psi_report import generate_psi_report

MODEL_API_BASE_URL = os.getenv("MODEL_API_BASE_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./credit_risk_scores.db")

# Render's managed Postgres (and Heroku-style providers generally) hand out
# connection strings starting "postgres://", but SQLAlchemy 1.4+/psycopg2
# require the "postgresql://" scheme. Normalize so DATABASE_URL can be set
# to whatever the provider gives you, verbatim, without a manual edit.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _mask_database_url(url: str) -> str:
    """Redact credentials before ever putting a DB URL in an API response."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    return f"{scheme}://***@{rest}" if "@" in url else f"{scheme}://{rest}"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ScoreReport(Base):
    __tablename__ = "score_reports"

    id = Column(String, primary_key=True, index=True)
    file_name = Column(String, nullable=True)
    total_records = Column(Integer, nullable=False, default=0)
    successful = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    rows = relationship(
        "ScoreReportRow",
        back_populates="report",
        cascade="all, delete-orphan",
    )


class ScoreReportRow(Base):
    __tablename__ = "score_report_rows"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String, ForeignKey("score_reports.id"), nullable=False, index=True)

    row_index = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)

    limit_bal = Column(Float, nullable=False)
    sex = Column(Integer, nullable=False)
    education = Column(Integer, nullable=False)
    marriage = Column(Integer, nullable=False)
    age = Column(Integer, nullable=False)

    pay_0 = Column(Integer, nullable=False)
    pay_2 = Column(Integer, nullable=False)
    pay_3 = Column(Integer, nullable=False)
    pay_4 = Column(Integer, nullable=False)
    pay_5 = Column(Integer, nullable=False)
    pay_6 = Column(Integer, nullable=False)

    bill_amt1 = Column(Float, nullable=False)
    bill_amt2 = Column(Float, nullable=False)
    bill_amt3 = Column(Float, nullable=False)
    bill_amt4 = Column(Float, nullable=False)
    bill_amt5 = Column(Float, nullable=False)
    bill_amt6 = Column(Float, nullable=False)

    pay_amt1 = Column(Float, nullable=False)
    pay_amt2 = Column(Float, nullable=False)
    pay_amt3 = Column(Float, nullable=False)
    pay_amt4 = Column(Float, nullable=False)
    pay_amt5 = Column(Float, nullable=False)
    pay_amt6 = Column(Float, nullable=False)

    default_prediction = Column(Integer, nullable=True)
    probability_of_default = Column(Float, nullable=True)
    risk_label = Column(String, nullable=True)
    risk_band = Column(String, nullable=True)
    recommendation = Column(String, nullable=True)
    actual_default = Column(Integer, nullable=True)
    error = Column(String, nullable=True)

    report = relationship("ScoreReport", back_populates="rows")


Base.metadata.create_all(bind=engine)


def _ensure_row_columns():
    """Add columns introduced after the initial schema to an existing DB.

    SQLAlchemy's create_all() never alters existing tables, so databases
    created before risk_band/recommendation existed need a lightweight
    ALTER TABLE. Safe to run on every startup.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(score_report_rows)")
        }
        for column in ("risk_band", "recommendation"):
            if column not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE score_report_rows ADD COLUMN {column} VARCHAR"
                )
        conn.commit()


_ensure_row_columns()


app = FastAPI(
    title="Credit Risk Batch Scoring API",
    version="1.0.0",
    description="Batch scoring API with score report persistence",
)


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CreditRiskPayload(BaseModel):
    id: int
    limit_bal: float
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


class CreditRiskResult(BaseModel):
    default_prediction: int
    probability_of_default: float
    risk_band: str
    recommendation: str


class BatchScoreRequest(BaseModel):
    file_name: Optional[str] = None
    records: List[CreditRiskPayload] = Field(..., min_length=1)


class BatchScoredRecord(CreditRiskPayload):
    row_index: int
    default_prediction: int
    probability_of_default: float
    risk_band: str
    recommendation: str


class BatchScoreError(BaseModel):
    row_index: int
    id: Optional[int] = None
    error: str


class BatchScoreResponse(BaseModel):
    report_id: str
    total_records: int
    successful: int
    failed: int
    results: List[BatchScoredRecord]
    errors: List[BatchScoreError]


@app.get("/")
def root():
    return {"message": "Credit Risk Batch Scoring API is running"}


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "credit-risk-batch-api",
        "model_api_base_url": MODEL_API_BASE_URL,
        # Credentials redacted — this endpoint is public. Still useful to
        # confirm at a glance whether you're pointed at sqlite or Postgres.
        "database_url": _mask_database_url(DATABASE_URL),
    }


@app.get("/psi")
def get_psi():
    """Population Stability Index drift report.

    Computed here (not in credit-risk-api) because this service owns the
    scored-records database the comparison needs. Lazily loads its baseline
    on first call, so a missing baseline/AWS config degrades to a clear 503
    instead of ever blocking this service from starting.
    """
    try:
        return generate_psi_report(engine)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/batch-score", response_model=BatchScoreResponse)
async def batch_score(request: BatchScoreRequest, db: Session = Depends(get_db)):
    report_id = str(uuid.uuid4())

    report = ScoreReport(
        id=report_id,
        file_name=request.file_name,
        total_records=len(request.records),
        successful=0,
        failed=0,
    )

    db.add(report)
    db.commit()

    results: List[BatchScoredRecord] = []
    errors: List[BatchScoreError] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for index, record in enumerate(request.records, start=1):
            row = ScoreReportRow(
                report_id=report_id,
                row_index=index,
                customer_id=record.id,
                limit_bal=record.limit_bal,
                sex=record.sex,
                education=record.education,
                marriage=record.marriage,
                age=record.age,
                pay_0=record.pay_0,
                pay_2=record.pay_2,
                pay_3=record.pay_3,
                pay_4=record.pay_4,
                pay_5=record.pay_5,
                pay_6=record.pay_6,
                bill_amt1=record.bill_amt1,
                bill_amt2=record.bill_amt2,
                bill_amt3=record.bill_amt3,
                bill_amt4=record.bill_amt4,
                bill_amt5=record.bill_amt5,
                bill_amt6=record.bill_amt6,
                pay_amt1=record.pay_amt1,
                pay_amt2=record.pay_amt2,
                pay_amt3=record.pay_amt3,
                pay_amt4=record.pay_amt4,
                pay_amt5=record.pay_amt5,
                pay_amt6=record.pay_amt6,
            )

            try:
                response = await client.post(
                    f"{MODEL_API_BASE_URL}/score",
                    json=record.model_dump(),
                )

                response.raise_for_status()

                prediction = CreditRiskResult(**response.json())

                risk_label = (
                    "Likely to Default"
                    if prediction.default_prediction == 1
                    else "Not Likely to Default"
                )

                row.default_prediction = prediction.default_prediction
                row.probability_of_default = prediction.probability_of_default
                row.risk_label = risk_label
                row.risk_band = prediction.risk_band
                row.recommendation = prediction.recommendation

                results.append(
                    BatchScoredRecord(
                        row_index=index,
                        **record.model_dump(),
                        default_prediction=prediction.default_prediction,
                        probability_of_default=prediction.probability_of_default,
                        risk_band=prediction.risk_band,
                        recommendation=prediction.recommendation,
                    )
                )

            except Exception as exc:
                row.error = str(exc)

                errors.append(
                    BatchScoreError(
                        row_index=index,
                        id=record.id,
                        error=str(exc),
                    )
                )

            db.add(row)

    report.successful = len(results)
    report.failed = len(errors)

    db.commit()

    return BatchScoreResponse(
        report_id=report_id,
        total_records=len(request.records),
        successful=len(results),
        failed=len(errors),
        results=results,
        errors=errors,
    )


@app.get("/score-reports")
def list_score_reports(db: Session = Depends(get_db)):
    reports = (
        db.query(ScoreReport)
        .order_by(ScoreReport.created_at.desc())
        .all()
    )

    return [
        {
            "report_id": report.id,
            "file_name": report.file_name,
            "total_records": report.total_records,
            "successful": report.successful,
            "failed": report.failed,
            "created_at": report.created_at.isoformat(),
        }
        for report in reports
    ]


@app.get("/score-reports/{report_id}")
def get_score_report(report_id: str, db: Session = Depends(get_db)):
    report = db.query(ScoreReport).filter(ScoreReport.id == report_id).first()

    if not report:
        raise HTTPException(status_code=404, detail="Score report not found")

    rows = (
        db.query(ScoreReportRow)
        .filter(ScoreReportRow.report_id == report_id)
        .order_by(ScoreReportRow.row_index.asc())
        .all()
    )

    return {
        "report_id": report.id,
        "file_name": report.file_name,
        "total_records": report.total_records,
        "successful": report.successful,
        "failed": report.failed,
        "created_at": report.created_at.isoformat(),
        "rows": [
            {
                "row_index": row.row_index,
                "id": row.customer_id,
                "limit_bal": row.limit_bal,
                "sex": row.sex,
                "education": row.education,
                "marriage": row.marriage,
                "age": row.age,
                "pay_0": row.pay_0,
                "pay_2": row.pay_2,
                "pay_3": row.pay_3,
                "pay_4": row.pay_4,
                "pay_5": row.pay_5,
                "pay_6": row.pay_6,
                "bill_amt1": row.bill_amt1,
                "bill_amt2": row.bill_amt2,
                "bill_amt3": row.bill_amt3,
                "bill_amt4": row.bill_amt4,
                "bill_amt5": row.bill_amt5,
                "bill_amt6": row.bill_amt6,
                "pay_amt1": row.pay_amt1,
                "pay_amt2": row.pay_amt2,
                "pay_amt3": row.pay_amt3,
                "pay_amt4": row.pay_amt4,
                "pay_amt5": row.pay_amt5,
                "pay_amt6": row.pay_amt6,
                "default_prediction": row.default_prediction,
                "probability_of_default": row.probability_of_default,
                "risk_band": row.risk_band,
                "recommendation": row.recommendation,
                "error": row.error,
            }
            for row in rows
        ],
    }


@app.get("/score-reports/{report_id}/csv")
def download_score_report_csv(report_id: str, db: Session = Depends(get_db)):
    report = db.query(ScoreReport).filter(ScoreReport.id == report_id).first()

    if not report:
        raise HTTPException(status_code=404, detail="Score report not found")

    rows = (
        db.query(ScoreReportRow)
        .filter(ScoreReportRow.report_id == report_id)
        .order_by(ScoreReportRow.row_index.asc())
        .all()
    )

    output = StringIO()

    fieldnames = [
        "report_id",
        "row_index",
        "id",
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
        "default_prediction",
        "probability_of_default",
        "risk_band",
        "recommendation",
        "error",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                "report_id": report_id,
                "row_index": row.row_index,
                "id": row.customer_id,
                "limit_bal": row.limit_bal,
                "sex": row.sex,
                "education": row.education,
                "marriage": row.marriage,
                "age": row.age,
                "pay_0": row.pay_0,
                "pay_2": row.pay_2,
                "pay_3": row.pay_3,
                "pay_4": row.pay_4,
                "pay_5": row.pay_5,
                "pay_6": row.pay_6,
                "bill_amt1": row.bill_amt1,
                "bill_amt2": row.bill_amt2,
                "bill_amt3": row.bill_amt3,
                "bill_amt4": row.bill_amt4,
                "bill_amt5": row.bill_amt5,
                "bill_amt6": row.bill_amt6,
                "pay_amt1": row.pay_amt1,
                "pay_amt2": row.pay_amt2,
                "pay_amt3": row.pay_amt3,
                "pay_amt4": row.pay_amt4,
                "pay_amt5": row.pay_amt5,
                "pay_amt6": row.pay_amt6,
                "default_prediction": row.default_prediction,
                "probability_of_default": row.probability_of_default,
                "risk_band": row.risk_band,
                "recommendation": row.recommendation,
                "error": row.error,

            }
        )

    output.seek(0)

    filename = f"credit-risk-score-report-{report_id}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )