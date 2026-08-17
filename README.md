# Credit Risk Scoring & Prediction (Backend)

Two independently deployable FastAPI services behind a credit-risk scoring
system. See [credit-risk-frontend](https://github.com/Adedayo06/credit-risk-frontend_CORRECTED)
for the React/Vite client that talks to both.

## Architecture

```
                    ┌─────────────────────┐
  POST /score  ───▶ │  credit-risk-api     │   pure, stateless scorer:
                    │  (Model API)         │   loads the trained model,
                    └─────────────────────┘   no DB, no external deps

                    ┌─────────────────────┐
POST /batch-score──▶│  batch-api            │──▶ calls credit-risk-api's
GET  /score-reports │  owns the database    │    POST /score per record
GET  /psi           │  (SQLite locally /    │
                     │   Postgres in prod)   │
                    └─────────────────────┘
```

Two separate services on purpose: `credit-risk-api` is a stateless model
scorer that could be scaled/redeployed independently of anything else.
`batch-api` owns all persistence (score-report history) and drift monitoring
(PSI), since those need a database and `credit-risk-api` deliberately doesn't
have one.

- **`credit-risk-api`** — `GET /`, `GET /health`, `GET /metrics`,
  `POST /score`.
- **`batch-api`** — `GET /health`, `POST /batch-score`, `GET /score-reports`,
  `GET /score-reports/{id}`, `GET /score-reports/{id}/csv`, `GET /psi`.
  Calls `credit-risk-api` over HTTP (`MODEL_API_BASE_URL`) for each record in
  a batch.

## Live demo

- Model API: _add your Render URL here once deployed_
- Batch API: _add your Render URL here_
- Frontend: _see the frontend repo_

## Running locally

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

This starts the Model API on :8000 and Batch API on :8001. Or run each
manually:

```bash
cd credit-risk-api && uvicorn app.main:app --reload --port 8000
cd batch-api && uvicorn main:app --reload --port 8001
```

Then run the frontend (see that repo) — its dev-server proxy expects these
exact ports.

### Model drift (PSI) locally

`GET /psi` on `batch-api` needs a baseline feature distribution to compare
against. Either:

- Run `python scripts/export_baseline.py` once (needs AWS credentials for the
  `newmlopsbucket` S3 bucket used during training) to generate
  `batch-api/model_drift/baseline.csv`, or
- Set `BASELINE_S3_BUCKET` (+ AWS credentials) as env vars to load it from S3
  on each request instead.

Without either, `GET /psi` returns a clean `503` rather than failing to
start — every other endpoint on both services works regardless.

## Deploying (Render)

`render.yaml` at the repo root is a Render Blueprint that deploys both
services plus a managed Postgres database in one shot:

1. In the Render dashboard: **New → Blueprint**, point it at this repo.
2. Render will prompt for a couple of values it can't infer on its own:
   - `ALLOWED_ORIGINS` on both services (your Vercel frontend URL, once you
     have it — comma-separated if you have more than one).
   - `MODEL_API_BASE_URL` on `batch-api` (the Model API's Render URL — deploy
     that service first, or just fill this in and redeploy `batch-api` once
     you know it).
3. `DATABASE_URL` on `batch-api` is wired automatically to the Postgres
   instance the Blueprint provisions — no manual value needed. Score-report
   history persists across deploys/restarts.

Each service's Dockerfile respects Render's `$PORT` env var automatically.

### Environment variables

| Service | Variable | Purpose | Default |
|---|---|---|---|
| credit-risk-api | `ALLOWED_ORIGINS` | comma-separated CORS origins | `http://localhost:5173,http://127.0.0.1:5173` |
| batch-api | `ALLOWED_ORIGINS` | comma-separated CORS origins | same |
| batch-api | `MODEL_API_BASE_URL` | credit-risk-api's base URL | `http://127.0.0.1:8000` |
| batch-api | `DATABASE_URL` | SQLAlchemy connection string (sqlite or postgres) | `sqlite:///./credit_risk_scores.db` |
| batch-api | `BASELINE_S3_BUCKET` / `BASELINE_S3_KEY` | optional S3 fallback for the PSI baseline if `model_drift/baseline.csv` isn't present | unset |

## Repo layout

```
credit-risk-api/       Model API — pure stateless scorer
  app/main.py
  model/                trained model + its eval metrics
  Dockerfile

batch-api/              Batch API — owns the DB, calls credit-risk-api
  main.py
  model_drift/          PSI drift report (baseline.csv + calculation)
  Dockerfile

scripts/
  export_baseline.py    one-off: pull the PSI baseline from S3 to a local CSV

notebooks/               training/exploration notebooks — not part of either
                          deployed service

render.yaml              Render Blueprint: both services + a Postgres DB
```

## Notes

- Both APIs are independently versioned FastAPI apps — there's no shared
  code between them by design, so either can be redeployed or scaled without
  touching the other.
- The trained model (`credit-risk-api/model/credit_risk_model.joblib`) and
  its evaluation metrics (`metrics.json`) are committed directly — no model
  registry involved. Retrain via `notebooks/Training.ipynb` and replace both
  files to update the deployed model.
