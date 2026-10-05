"""Pronostico por banco: seleccion de bancos, features, ausencia de mirada hacia adelante y
deteccion de una reversion a la media sintetica. Ninguno usa la red."""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import banks as B
from cmf_delinquency import forecast as F
from cmf_delinquency.pipeline import _round

ROOT = Path(__file__).resolve().parents[1]


def _months(n, start="2016-01-01"):
    return pd.date_range(start, periods=n, freq="MS")


def _panel(spec, n=120):
    """spec: {banco: (nivel de mora %, colocaciones MM$, meses disponibles)}."""
    rows = []
    for date in _months(n):
        for bank, (pct, loans, months) in spec.items():
            if (date - pd.Timestamp("2016-01-01")).days // 30 >= months:
                continue
            rows.append({"date": date, "bank": bank, "is_system": False, "total": pct, "mora90_mm": pct / 100 * loans})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- seleccion
def test_eligible_banks_keeps_large_and_long_and_drops_small_or_short():
    panel = _panel({"Grande": (2.0, 1000.0, 120), "Mediano": (2.0, 500.0, 120), "Chico": (2.0, 2.0, 120), "Corto": (2.0, 1000.0, 40)})
    assert B.eligible_banks(panel) == ["Grande", "Mediano"]


def test_eligible_banks_respects_the_thresholds():
    panel = _panel({"A": (2.0, 1000.0, 120), "B": (2.0, 1000.0, 90)})
    assert B.eligible_banks(panel, min_months=100) == ["A"]
    assert B.eligible_banks(panel, min_months=80) == ["A", "B"]


def test_wide_series_interpolates_a_single_month_gap_but_not_two():
    panel = _panel({"A": (2.0, 1000.0, 120)})
    panel.loc[(panel["date"] == "2016-04-01"), "total"] = np.nan
    panel.loc[(panel["date"] == "2016-07-01") | (panel["date"] == "2016-08-01"), "total"] = np.nan
    wide = B.wide_series(panel, ["A"])
    assert not np.isnan(wide.loc["2016-04-01", "A"])
    assert np.isnan(wide.loc["2016-08-01", "A"])  # el segundo mes seguido queda sin rellenar


# ------------------------------------------------------------------------ features
def test_pooled_features_by_hand():
    idx = _months(6)
    wide = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "B": [2.0] * 6}, index=idx)
    system = pd.Series([1.5, 1.5, 2.0, 2.0, 2.5, 2.5], index=idx)
    f = B.pooled_features(wide, system)
    assert f["mom3"]["A"].iloc[4] == 3.0 and f["mom3"]["B"].iloc[4] == 0.0
    assert f["gap"]["A"].iloc[2] == pytest.approx(1.0) and f["gap"]["B"].iloc[2] == pytest.approx(0.0)
    assert f["sys_mom3"]["A"].iloc[5] == pytest.approx(0.5)
    assert np.isnan(f["mom3"]["A"].iloc[1])


# --------------------------------------------------------------- generador sintetico
def _reverting_world(n=130, reversion=0.15, seed=0, n_banks=6, idiosyncratic=0.12):
    """Cada banco tira hacia el sistema una fraccion ``reversion`` de su brecha cada mes.

    Los choques propios del banco (``idiosyncratic``) mantienen las brechas relevantes durante toda
    la muestra; sin ellos la brecha inicial se cierra en pocos meses y despues no hay nada que predecir.
    """
    rng = np.random.default_rng(seed)
    idx = _months(n)
    system = pd.Series(2 + np.cumsum(rng.normal(0, 0.04, n)), index=idx)
    banks = {}
    for b in range(n_banks):
        y = np.zeros(n)
        y[0] = system.iloc[0] + rng.normal(0, 1.0)
        for t in range(1, n):
            gap = y[t - 1] - system.iloc[t - 1]
            y[t] = y[t - 1] - reversion * gap + (system.iloc[t] - system.iloc[t - 1]) + rng.normal(0, idiosyncratic)
        banks[f"B{b}"] = y
    return pd.DataFrame(banks, index=idx), system


def test_pooled_gap_detects_a_real_mean_reversion():
    wide, system = _reverting_world(reversion=0.15)
    errors = B.common_support(B.pooled_rolling_origin(wide, system, horizons=(6,)))
    pooled = B.per_origin(errors)
    ratio, lo, hi = F.rmae_ci(pooled, "pooled_gap", 6, n_boot=300)
    assert hi < 1.0, (ratio, lo, hi)  # con reversion real, usar la brecha le gana al ingenuo
    vs_mom = F.rmae_ci(pooled, "pooled_gap", 6, n_boot=300, baseline="pooled_momentum")
    assert vs_mom[2] < 1.0


def test_pooled_gap_does_not_invent_a_reversion_that_is_not_there():
    wide, system = _reverting_world(reversion=0.0)
    errors = B.common_support(B.pooled_rolling_origin(wide, system, horizons=(6,)))
    pooled = B.per_origin(errors)
    ratio, lo, hi = F.rmae_ci(pooled, "pooled_gap", 6, n_boot=300)
    assert lo > 0.9  # sin reversion, la brecha no puede ayudar de forma clara


def test_pooled_forecast_never_looks_ahead():
    wide, system = _reverting_world(n=110)
    full = B.pooled_rolling_origin(wide, system, horizons=(3,))
    row = full[(full["model"] == "pooled_gap") & (full["bank"] == "B0")].iloc[8]
    tampered = wide.copy()
    tampered.loc[row["target"], "B0"] += 50.0  # el objetivo mismo
    again = B.pooled_rolling_origin(tampered, system, horizons=(3,))
    same = again[(again["model"] == "pooled_gap") & (again["bank"] == "B0") & (again["origin"] == row["origin"])]
    assert same["pred"].iloc[0] == pytest.approx(row["pred"])


def test_forecast_targets_the_right_month():
    wide, system = _reverting_world(n=100)
    errors = B.pooled_rolling_origin(wide, system, horizons=(1, 6))
    months = (errors["target"].dt.year * 12 + errors["target"].dt.month) - (errors["origin"].dt.year * 12 + errors["origin"].dt.month)
    assert (months == errors["h"]).all()


# --------------------------------------------------------------------- agregaciones
def test_common_support_keeps_only_cells_where_every_model_exists():
    base = {"bank": "A", "origin": pd.Timestamp("2020-01-01"), "h": 1, "abs_err": 1.0}
    errors = pd.DataFrame(
        [{**base, "model": m} for m in B.ALL_MODELS]
        + [{**base, "origin": pd.Timestamp("2020-02-01"), "model": m} for m in B.ALL_MODELS[:3]]
    )
    out = B.common_support(errors)
    assert set(out["origin"]) == {pd.Timestamp("2020-01-01")} and len(out) == len(B.ALL_MODELS)


def test_per_origin_averages_across_banks():
    errors = pd.DataFrame({
        "bank": ["A", "B"], "origin": pd.Timestamp("2020-01-01"), "h": 1, "model": "naive", "abs_err": [1.0, 3.0],
    })
    assert B.per_origin(errors)["abs_err"].iloc[0] == 2.0


def test_bank_table_ratio_by_hand():
    rows = []
    for bank, naive, model in (("A", 2.0, 1.0), ("B", 1.0, 1.5)):
        for o in range(3):
            rows += [{"bank": bank, "origin": o, "h": 6, "model": "naive", "abs_err": naive},
                     {"bank": bank, "origin": o, "h": 6, "model": "pooled_gap", "abs_err": model}]
    table = B.bank_table(pd.DataFrame(rows), "pooled_gap", 6)
    assert table.loc["A", "rmae"] == 0.5 and table.loc["B", "rmae"] == 1.5
    assert list(table.index) == ["A", "B"]  # ordenado de mejor a peor


# --------------------------------------------------------------- JSON estricto
def test_round_turns_nan_and_inf_into_none():
    out = _round({"a": float("nan"), "b": [float("inf"), 1.23456], "c": {"d": float("-inf")}})
    assert out == {"a": None, "b": [None, 1.2346], "c": {"d": None}}


def test_results_json_is_strict_json():
    """json.dumps escribe NaN por defecto, que JavaScript y jq rechazan."""
    def reject(constant):
        raise ValueError(f"constante no valida en JSON estricto: {constant}")

    text = (ROOT / "reports" / "results.json").read_text(encoding="utf-8")
    data = json.loads(text, parse_constant=reject)
    assert "bancos_pronostico" in data
    assert not any(isinstance(v, float) and math.isnan(v) for v in data["bancos_pronostico"]["mae_naive_pp"].values())
