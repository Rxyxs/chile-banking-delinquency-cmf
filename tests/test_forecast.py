import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import forecast as F


def _series(values, start="2015-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_naive_repeats_the_last_value():
    assert F.forecast_naive(_series([1, 2, 3]), 5) == 3.0


def test_drift_extrapolates_a_straight_line_exactly():
    s = _series(np.arange(40) * 0.5)
    assert F.forecast_drift(s, 4) == pytest.approx(s.iloc[-1] + 4 * 0.5)


def test_seasonal_naive_returns_the_same_month_of_the_previous_year():
    s = _series(np.arange(36))
    for h in (1, 6, 12):
        expected = s.iloc[len(s) - 1 + h - 12]
        assert F.forecast_seasonal_naive(s, h) == expected


def test_seasonal_naive_at_12_months_equals_naive():
    s = _series(np.random.default_rng(0).normal(size=40))
    assert F.forecast_seasonal_naive(s, 12) == F.forecast_naive(s, 12)


def test_ets_and_arima_return_finite_numbers():
    s = _series(2 + 0.1 * np.sin(np.arange(80) / 5))
    assert np.isfinite(F.forecast_ets(s, 3))
    assert np.isfinite(F.forecast_arima(s, 3))


def test_rolling_origin_never_uses_the_future():
    s = _series(np.arange(70, dtype=float))
    errors = F.rolling_origin(s, horizons=(1, 3), min_train=60)
    assert (errors["target"] > errors["origin"]).all()
    naive = errors[(errors["model"] == "naive") & (errors["h"] == 3)]
    # en una recta de pendiente 1 el error del ingenuo a 3 pasos es exactamente 3
    assert naive["abs_err"].eq(3.0).all()


def test_rolling_origin_counts_origins_per_horizon():
    s = _series(np.arange(75, dtype=float))
    errors = F.rolling_origin(s, horizons=(1, 12), min_train=60)
    n = errors[(errors["model"] == "naive")].groupby("h").size()
    # h=1: orígenes 60..74 (15). h=12: el objetivo debe caer dentro de la serie -> 60..63 (4)
    assert n[1] == 15 and n[12] == 4


def test_horizon_without_evaluable_origins_is_skipped():
    s = _series(np.arange(70, dtype=float))
    errors = F.rolling_origin(s, horizons=(12,), min_train=60)
    assert errors.empty


def test_relative_mae_of_naive_is_one():
    s = _series(np.random.default_rng(1).normal(2, 0.1, 75))
    errors = F.rolling_origin(s, horizons=(1,), min_train=60)
    rel = F.relative_mae(errors, ["h"])
    assert rel.loc[1, "naive"] == 1.0
    assert rel.loc[1, "n"] == 15


def test_a_perfect_model_beats_the_naive_baseline():
    errors = pd.DataFrame(
        {
            "origin": pd.date_range("2020-01-01", periods=40, freq="MS").tolist() * 2,
            "h": 3,
            "model": ["naive"] * 40 + ["perfect"] * 40,
            "abs_err": [1.0] * 40 + [0.0] * 40,
        }
    )
    point, lo, hi = F.rmae_ci(errors, "perfect", 3)
    assert point == 0.0 and lo == 0.0 and hi == 0.0


def test_rmae_ci_brackets_the_point_estimate_and_is_reproducible():
    rng = np.random.default_rng(2)
    n = 60
    errors = pd.DataFrame(
        {
            "origin": pd.date_range("2018-01-01", periods=n, freq="MS").tolist() * 2,
            "h": 3,
            "model": ["naive"] * n + ["m"] * n,
            "abs_err": np.concatenate([rng.uniform(0.5, 1.5, n), rng.uniform(0.4, 1.4, n)]),
        }
    )
    a = F.rmae_ci(errors, "m", 3, n_boot=500, seed=7)
    b = F.rmae_ci(errors, "m", 3, n_boot=500, seed=7)
    assert a == b
    assert a[1] <= a[0] <= a[2]


def test_rmae_ci_with_few_origins_is_nan():
    errors = pd.DataFrame(
        {"origin": pd.date_range("2020-01-01", periods=5, freq="MS").tolist() * 2, "h": 1,
         "model": ["naive"] * 5 + ["m"] * 5, "abs_err": 1.0}
    )
    assert all(np.isnan(x) for x in F.rmae_ci(errors, "m", 1))


def test_best_model_per_horizon():
    rel = pd.DataFrame({"naive": [1.0, 1.0], "drift": [1.2, 0.9], "arima_111": [0.8, 1.1]}, index=[1, 3])
    assert list(F.best_model_per_horizon(rel)) == ["arima_111", "drift"]
