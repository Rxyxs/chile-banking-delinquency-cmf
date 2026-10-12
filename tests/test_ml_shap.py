"""LightGBM + SHAP: sin mirar el futuro, aditividad exacta de SHAP y reproducibilidad."""
import json
from pathlib import Path

import pandas as pd
import pytest

from cmf_delinquency import analysis as A
from cmf_delinquency.models import ml_shap as ML

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data(panel):
    macro = pd.read_csv(ROOT / "data" / "macro_indicators.csv", parse_dates=["month"]).set_index("month")
    return ML.build_panel(panel, macro, A.system_series(panel)["consumo"], "consumo")


def test_targets_are_future_changes_and_features_are_past(data):
    bank = data["bank"].iloc[0]
    d = data[data["bank"] == bank].set_index("date")
    t = d.index[20]
    assert d.at[t, "y_3"] == pytest.approx(d.at[t + pd.DateOffset(months=3), "nivel"] - d.at[t, "nivel"])
    assert d.at[t, "mom3"] == pytest.approx(d.at[t, "nivel"] - d.at[t - pd.DateOffset(months=3), "nivel"])
    assert not data[list(ML.FEATURES)].isna().any().any()


def test_rolling_origin_never_trains_on_unknown_outcomes(data, monkeypatch):
    seen = []
    real = ML._lgbm

    class Spy:
        def __init__(self):
            self.m = real()

        def fit(self, x, y):
            seen.append(len(x))
            self.m.fit(x, y)
            return self

        def predict(self, x):
            return self.m.predict(x)

    monkeypatch.setattr(ML, "_lgbm", Spy)
    errors = ML.rolling_origin(data, horizons=(6,), first_origin="2026-01-01")
    origins = sorted(errors["origin"].unique())
    assert len(origins) == len(seen) > 0
    for origin, n in zip(origins, seen):
        known = data[data["date"] <= pd.Timestamp(origin) - pd.DateOffset(months=6)].dropna(subset=["y_6"])
        assert n == len(known)
    assert set(errors["model"]) == {"naive", "ols_agrupado", "lightgbm"}


def test_backtest_table_reports_relative_errors(data):
    table = ML.backtest_table(ML.rolling_origin(data, horizons=(3,), first_origin="2024-01-01"))
    assert set(table["model"]) == {"ols_agrupado", "lightgbm"}
    assert (table["lo"] <= table["rmae"]).all() and (table["rmae"] <= table["hi"]).all()


def test_shap_is_exactly_additive_and_reproducible(data):
    _, rep1 = ML.explain(data, h=6)
    _, rep2 = ML.explain(data, h=6)
    assert max(x["error_aditividad"] for x in rep1.local) < 1e-9
    for item in rep1.local:
        total = item["base_value"] + sum(item["aportes_grupo"].values())
        assert total == pytest.approx(item["prediction_pp"], abs=1e-9)
    assert rep1.global_importance.equals(rep2.global_importance)
    assert {x["date"] for x in rep1.local} == {f"{data['date'].max():%Y-%m}"}


def test_shap_groups_cover_every_feature_once():
    covered = [f for fs in ML.GROUPS.values() for f in fs]
    assert sorted(covered) == sorted(ML.FEATURES)


def test_artifacts_are_written(data, tmp_path):
    _, rep = ML.explain(data, h=6)
    table = pd.DataFrame([{"h": 6, "model": "lightgbm", "rmae": 1.0}])
    payload = json.loads(ML.export_json(rep, table, tmp_path / "shap.json").read_text(encoding="utf-8"))
    assert payload["horizonte_meses"] == 6 and len(payload["explicaciones_locales"]) == len(rep.local)
    assert ML.shap_summary_plot(rep, tmp_path / "s.png").stat().st_size > 10_000
    assert ML.shap_local_plot(rep, rep.local[0]["bank"], tmp_path / "l.png").stat().st_size > 5_000
