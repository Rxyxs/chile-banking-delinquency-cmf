"""Indicadores macro: descarga (simulada), rezagos de publicacion, correlaciones rezagadas y
pronostico directo. Ninguno de estos tests usa la red."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import analysis as A
from cmf_delinquency import forecast as F
from cmf_delinquency import macro as M

ROOT = Path(__file__).resolve().parents[1]


def _months(n, start="2016-01-01"):
    return pd.date_range(start, periods=n, freq="MS")


# ------------------------------------------------------------------------------- datos macro
def test_monthly_series_keeps_the_last_observation_of_each_month():
    raw = pd.DataFrame({"date": pd.to_datetime(["2020-01-05", "2020-01-28", "2020-02-10"]), "value": [1.0, 2.0, 3.0]})
    s = M.monthly_series(raw, "tpm_pct")
    assert s.to_dict() == {pd.Timestamp("2020-01-01"): 2.0, pd.Timestamp("2020-02-01"): 3.0}
    assert s.name == "tpm_pct"


def test_monthly_series_orders_unsorted_input_before_taking_the_last():
    raw = pd.DataFrame({"date": pd.to_datetime(["2020-01-28", "2020-01-05"]), "value": [9.0, 1.0]})
    assert M.monthly_series(raw, "x").iloc[0] == 9.0


def test_publication_lag_shifts_only_the_late_series():
    macro = pd.DataFrame(
        {"unemployment_pct": [1.0, 2.0, 3.0], "tpm_pct": [10.0, 20.0, 30.0], "imacec_yoy_pct": [5.0, 6.0, 7.0]},
        index=_months(3),
    )
    out = M.apply_publication_lag(macro)
    assert np.isnan(out["unemployment_pct"].iloc[0]) and out["unemployment_pct"].iloc[1] == 1.0
    assert out["tpm_pct"].tolist() == [10.0, 20.0, 30.0]
    assert np.isnan(out["imacec_yoy_pct"].iloc[0]) and out["imacec_yoy_pct"].iloc[2] == 6.0
    assert macro["unemployment_pct"].iloc[0] == 1.0  # no modifica el original


def test_complete_months_drops_rows_with_any_gap():
    macro = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [1.0, 2.0, 3.0]}, index=_months(3))
    assert len(M.complete_months(macro)) == 2


def test_download_macro_builds_a_monthly_table_without_the_network(monkeypatch):
    def fake_fetch(code, year, session):
        return [{"fecha": f"{year}-{m:02d}-01T03:00:00.000Z", "valor": float(m + (code == "tpm") * 10)} for m in (1, 2)]

    monkeypatch.setattr(M, "_fetch_year", fake_fetch)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    out = M.download_macro(last_year=M.FIRST_YEAR + 1)
    assert list(out.columns) == ["unemployment_pct", "tpm_pct", "imacec_yoy_pct"]
    assert len(out) == 4 and out.index.name == "month"
    assert out["tpm_pct"].iloc[0] == 11.0


def test_committed_macro_table_is_sane():
    macro = pd.read_csv(ROOT / "data" / "macro_indicators.csv", parse_dates=["month"]).set_index("month")
    assert list(macro.columns) == ["unemployment_pct", "tpm_pct", "imacec_yoy_pct"]
    assert macro.index.is_monotonic_increasing and not macro.index.duplicated().any()
    full = pd.date_range(macro.index.min(), macro.index.max(), freq="MS")
    assert len(full) == len(macro)  # sin meses salteados
    assert macro["unemployment_pct"].dropna().between(3, 20).all()
    assert macro["tpm_pct"].dropna().between(0, 15).all()
    assert macro["imacec_yoy_pct"].dropna().between(-25, 25).all()


# ---------------------------------------------------------------------------- lead_lag
def test_lead_lag_peaks_at_the_true_lead():
    rng = np.random.default_rng(0)
    n = 160
    driver = pd.Series(np.cumsum(rng.normal(size=n)), index=_months(n))
    mora = driver.shift(5).fillna(0) * 0.8 + rng.normal(0, 0.05, n)
    mora = pd.Series(mora.to_numpy(), index=driver.index)
    ll = A.lead_lag(mora, driver, max_lag=12)
    assert int(ll.loc[ll["corr"].idxmax(), "lag"]) == 5
    assert ll["corr"].max() > 0.9


def test_lead_lag_is_negative_for_an_inverse_relation():
    rng = np.random.default_rng(1)
    n = 160
    driver = pd.Series(np.cumsum(rng.normal(size=n)), index=_months(n))
    mora = pd.Series((-driver.shift(3).fillna(0)).to_numpy(), index=driver.index)
    ll = A.lead_lag(mora, driver, max_lag=6)
    assert ll.loc[ll["corr"].idxmin(), "lag"] == 3 and ll["corr"].min() < -0.9


@pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")
def test_lead_lag_reports_the_sample_size_and_uses_changes_not_levels():
    n = 60
    idx = _months(n)
    trend_a = pd.Series(np.arange(n, dtype=float), index=idx)
    trend_b = pd.Series(np.arange(n, dtype=float) * 3 + 7, index=idx)
    ll = A.lead_lag(trend_a, trend_b, max_lag=2)
    assert ll["n"].iloc[0] == n - 12
    # dos tendencias lineales tienen cambios a 12 meses constantes: sin varianza, sin correlacion util
    assert ll["corr"].isna().all()


# ---------------------------------------------------------------------------- features
def test_macro_features_by_hand():
    idx = _months(12)
    y = pd.Series(np.arange(12, dtype=float), index=idx)
    macro = pd.DataFrame(
        {"unemployment_pct": np.arange(12) * 2.0, "tpm_pct": np.arange(12) * 0.5, "imacec_yoy_pct": np.arange(12) - 5.0},
        index=idx,
    )
    f = F.macro_features(y, macro)
    assert f["momentum_3m"].iloc[5] == 3.0
    assert f["d6_unemployment"].iloc[8] == 12.0  # 16 - 4
    assert f["d6_tpm"].iloc[8] == 3.0
    assert f["imacec_yoy"].iloc[4] == -1.0
    assert np.isnan(f["momentum_3m"].iloc[2]) and np.isnan(f["d6_unemployment"].iloc[5])


# ------------------------------------------------------------------ pronostico directo
def _synthetic(n=130, informative=True, seed=0):
    """y reacciona a un indicador con 3 meses de rezago (si ``informative``); si no, ruido puro."""
    rng = np.random.default_rng(seed)
    idx = _months(n)
    unemp = np.cumsum(rng.normal(0, 0.4, n)) + 8
    d6 = pd.Series(unemp).diff(6).to_numpy()
    y = np.zeros(n)
    for t in range(1, n):
        shock = 0.15 * d6[t - 3] if informative and t >= 9 else 0.0
        y[t] = y[t - 1] + np.nan_to_num(shock) + rng.normal(0, 0.02)
    macro = pd.DataFrame({"unemployment_pct": unemp, "tpm_pct": rng.normal(size=n), "imacec_yoy_pct": rng.normal(size=n)}, index=idx)
    return pd.Series(y + 2.0, index=idx), macro


def test_direct_forecast_targets_the_right_month():
    y, macro = _synthetic()
    errors = F.direct_rolling_origin(y, macro, horizons=(1, 3))
    diff = (errors["target"].dt.year * 12 + errors["target"].dt.month) - (errors["origin"].dt.year * 12 + errors["origin"].dt.month)
    assert (diff == errors["h"]).all()


def test_direct_forecast_never_looks_ahead():
    """El pronostico de un origen no cambia si se borra todo lo posterior al ultimo dato que ese
    origen podia conocer (el objetivo mismo incluido)."""
    y, macro = _synthetic(120)
    full = F.direct_rolling_origin(y, macro, horizons=(3,))
    row = full[(full["model"] == "momentum+macro")].iloc[10]
    cut = y.loc[: row["target"]]  # incluye el objetivo; se descarta lo posterior
    truncated = F.direct_rolling_origin(cut, macro, horizons=(3,))
    same = truncated[(truncated["model"] == "momentum+macro") & (truncated["origin"] == row["origin"])]
    assert same["pred"].iloc[0] == pytest.approx(row["pred"])
    # y la prediccion tampoco depende del valor del objetivo
    tampered = y.copy()
    tampered.loc[row["target"]] += 100.0
    again = F.direct_rolling_origin(tampered, macro, horizons=(3,))
    same2 = again[(again["model"] == "momentum+macro") & (again["origin"] == row["origin"])]
    assert same2["pred"].iloc[0] == pytest.approx(row["pred"])


def test_macro_helps_when_the_signal_is_real_and_not_otherwise():
    for informative in (True, False):
        y, macro = _synthetic(informative=informative)
        direct = F.direct_rolling_origin(y, macro, horizons=(3,))
        base = F.rolling_origin(y, horizons=(3,))
        al = F.align_with_naive(direct, base)
        ratio, lo, hi = F.rmae_ci(al, "momentum+unemployment", 3, n_boot=300, baseline="momentum")
        if informative:
            assert hi < 1.0, (ratio, lo, hi)
        else:
            assert lo > 0.85  # sin senal, agregar macro no puede ayudar de forma clara


def test_align_with_naive_keeps_only_origins_where_every_direct_model_exists():
    direct = pd.DataFrame(
        {"origin": pd.to_datetime(["2020-01-01"] * 3 + ["2020-02-01"] * 2), "h": 1,
         "model": list(F.DIRECT_MODELS) + list(F.DIRECT_MODELS)[:2], "abs_err": 1.0}
    )
    naive = pd.DataFrame({"origin": pd.to_datetime(["2020-01-01", "2020-02-01"]), "h": 1, "model": "naive", "abs_err": 2.0})
    out = F.align_with_naive(direct, naive)
    assert set(out["origin"]) == {pd.Timestamp("2020-01-01")}
    assert (out["model"] == "naive").sum() == 1 and len(out) == 4


def test_rmae_ci_accepts_a_non_naive_baseline():
    n = 40
    errors = pd.DataFrame(
        {"origin": list(_months(n)) * 2, "h": 1, "model": ["a"] * n + ["b"] * n,
         "abs_err": [1.0] * n + [2.0] * n}
    )
    point, lo, hi = F.rmae_ci(errors, "b", 1, n_boot=100, baseline="a")
    assert point == 2.0 and lo == 2.0 and hi == 2.0
