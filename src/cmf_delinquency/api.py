"""API REST del motor de estres (FastAPI).

El motor se calibra una sola vez al arrancar, con el panel CMF y las series macro versionadas; cada
peticion solo simula. Endpoints:

* ``GET  /health``                : estado y fecha del ultimo dato.
* ``GET  /model``                 : coeficientes del modelo satelite por cartera.
* ``GET  /scenarios``             : escenarios predefinidos (base, historicos, hipotetico).
* ``POST /simulate/stress-test``  : simula un escenario arbitrario.

Uso:
    uvicorn cmf_delinquency.api:app --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import stress_test as S

DATA_DIR = Path(os.environ.get("CMF_DATA_DIR", S.ROOT / "data"))
Portfolio = Literal["total", "comercial", "consumo", "vivienda"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    panel_csv, macro_csv = DATA_DIR / "panel_mora90.csv", DATA_DIR / "macro_indicators.csv"
    app.state.engine = S.CreditRiskStressEngine.from_csv(panel_csv, macro_csv)
    app.state.macro = pd.read_csv(macro_csv, parse_dates=["month"]).set_index("month")
    yield


app = FastAPI(
    title="Chile banking delinquency stress test",
    version="1.0.0",
    description="Prueba de tension macro de la mora 90+ del sistema bancario chileno, calibrada con datos de la CMF.",
    lifespan=lifespan,
)


class StressRequest(BaseModel):
    scenario_name: str = Field(default="Escenario personalizado", max_length=120)
    tpm_shock_bp: float = Field(default=200.0, ge=-1500, le=1500, description="Cambio de la TPM en 12 meses (pb)")
    unemployment_delta_pp: float = Field(default=1.0, ge=-10, le=10, description="Cambio del desempleo en 12 meses (pp)")
    imacec_growth: float = Field(default=-1.0, ge=-30, le=30, description="IMACEC, variacion anual (%)")
    portfolio: Portfolio = "total"
    num_simulations: int = Field(default=10_000, ge=100, le=100_000)
    seed: int | None = Field(default=42, description="Semilla; null = no reproducible")
    lgd_mean: float = Field(default=S.LGD_MEAN, gt=0.0, lt=1.0)
    lgd_sd: float = Field(default=S.LGD_SD, gt=0.0, lt=0.5)


class StressResponse(BaseModel):
    scenario_name: str
    portfolio: str
    as_of: str
    n_sims: int
    current_mora_pct: float
    point_delta_pp: float
    mean_mora_pct: float
    p05_mora_pct: float
    p95_mora_pct: float
    p99_mora_pct: float
    prob_increase: float
    out_of_sample_range: list[str]
    ead_mm: float | None = None
    current_loss_mm: float | None = None
    mean_loss_mm: float | None = None
    p95_loss_mm: float | None = None
    p99_loss_mm: float | None = None
    mean_extra_loss_mm: float | None = None
    var99_extra_loss_mm: float | None = None
    unexpected_loss_99_mm: float | None = None


def _engine(request: Request) -> S.CreditRiskStressEngine:
    return request.app.state.engine


@app.get("/health")
def health(request: Request) -> dict:
    engine = _engine(request)
    return {"status": "ok", "service": "cmf-delinquency-stress", "data_as_of": engine.as_of, "portfolios": list(engine.fits)}


@app.get("/model")
def model(request: Request) -> dict:
    engine = _engine(request)
    return {
        "as_of": engine.as_of,
        "lag_months": S.LAG,
        "excluded_from_fit": list(S.COVID_RELIEF),
        "ead_mm": engine.ead_mm,
        "fits": engine.summary().reset_index().to_dict(orient="records"),
    }


@app.get("/scenarios")
def scenarios(request: Request) -> list[dict]:
    return [sc.__dict__ for sc in S.default_scenarios(request.app.state.macro)]


@app.post("/simulate/stress-test", response_model=StressResponse)
def simulate(req: StressRequest, request: Request) -> StressResponse:
    scenario = S.StressScenario(req.scenario_name, req.tpm_shock_bp, req.unemployment_delta_pp, req.imacec_growth)
    try:
        result = _engine(request).simulate(scenario, req.portfolio, n_sims=req.num_simulations, seed=req.seed,
                                           lgd_mean=req.lgd_mean, lgd_sd=req.lgd_sd)
    except ValueError as exc:  # p.ej. LGD con desviacion imposible para su media
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StressResponse(**result)
