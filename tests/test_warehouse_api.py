"""Almacen DuckDB (construido en un directorio temporal) y API REST."""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cmf_delinquency import analysis as A
from cmf_delinquency import stress_test as S
from cmf_delinquency import warehouse as W
from cmf_delinquency.api import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("wh") / "test.duckdb"
    W.build_warehouse(path)
    return path


# ------------------------------------------------------------------------------- almacen
def test_warehouse_builds_every_model_and_is_idempotent(db, panel):
    counts = W.build_warehouse(db)
    assert set(counts) == {p.stem.split("_", 1)[1] for p in W.models()}
    assert counts["stg_morosidad"] == len(panel)
    assert counts == W.build_warehouse(db)


def test_quality_tests_pass_and_catch_duplicates(db):
    with duckdb.connect(str(db)) as con:
        assert all(v == 0 for v in W.run_quality_tests(con).values())
        con.execute("INSERT INTO stg_morosidad SELECT * FROM stg_morosidad LIMIT 1")
        assert W.run_quality_tests(con)["panel sin duplicados banco-mes"] == 1


def test_missing_csv_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        W.build_warehouse(tmp_path / "x.duckdb", panel_csv=tmp_path / "nope.csv")


def test_mart_factors_match_the_python_model(db, panel):
    """La version SQL de los factores debe coincidir con la que usa el motor de estres."""
    mart = W.query("SELECT * FROM mart_sistema_macro", db).set_index("month")
    mart.index = pd.to_datetime(mart.index)
    macro = pd.read_csv(ROOT / "data" / "macro_indicators.csv", parse_dates=["month"]).set_index("month")
    py = S.design(A.system_series(panel, fill=False)["total"], macro, exclude_covid=False)
    sql = mart.loc[py.index]
    np.testing.assert_allclose(sql["d12_total_pp"], py["y"], atol=1e-9)
    np.testing.assert_allclose(sql["d_tpm_pp_lag6"], py["d_tpm_pp"], atol=1e-9)
    np.testing.assert_allclose(sql["d_unemployment_pp_lag6"], py["d_unemployment_pp"], atol=1e-9)
    np.testing.assert_allclose(sql["imacec_yoy_pct_lag6"], py["imacec_yoy_pct"], atol=1e-9)


def test_fact_loans_match_implied_loans(db, panel):
    fct = W.query("SELECT month, bank, loans_mm FROM fct_mora_banco_mes WHERE loans_mm IS NOT NULL", db)
    banks = panel[~panel["is_system"]].assign(loans=lambda d: A.implied_loans(d)).dropna(subset=["loans"])
    assert len(fct) == len(banks)
    np.testing.assert_allclose(np.sort(fct["loans_mm"].to_numpy()), np.sort(banks["loans"].to_numpy()), rtol=1e-12)


# ------------------------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and "consumo" in body["portfolios"]


def test_model_and_scenarios(client):
    model = client.get("/model").json()
    assert set(model["lag_months"]) == {"total", "comercial", "consumo", "vivienda"} and len(model["fits"]) == 4
    assert all(lag in S.LAG_CANDIDATES for lag in model["lag_months"].values())
    assert len(client.get("/scenarios").json()) >= 3


def test_simulation_endpoint_matches_engine(client):
    payload = {"tpm_shock_bp": 300, "unemployment_delta_pp": 2, "imacec_growth": -3, "num_simulations": 2000, "seed": 1}
    body = client.post("/simulate/stress-test", json=payload).json()
    direct = app.state.engine.simulate(S.StressScenario("Escenario personalizado", 300, 2, -3), n_sims=2000, seed=1)
    assert body["mean_mora_pct"] == pytest.approx(direct["mean_mora_pct"])
    assert body["var99_extra_loss_mm"] == pytest.approx(direct["var99_extra_loss_mm"])


@pytest.mark.parametrize(
    "payload",
    [{"portfolio": "hipotecario"}, {"num_simulations": 10}, {"tpm_shock_bp": 99999}, {"lgd_mean": 0.05, "lgd_sd": 0.4}],
)
def test_invalid_requests_return_422(client, payload):
    assert client.post("/simulate/stress-test", json=payload).status_code == 422
