"""Motor de estres: recuperacion de coeficientes con datos sinteticos, propiedades de la simulacion
y calibracion con los datos reales versionados."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import analysis as A
from cmf_delinquency import stress_test as S

ROOT = Path(__file__).resolve().parents[1]


def _months(n, start="2014-01-01"):
    return pd.date_range(start, periods=n, freq="MS")


@pytest.fixture(scope="module")
def macro_real() -> pd.DataFrame:
    return pd.read_csv(ROOT / "data" / "macro_indicators.csv", parse_dates=["month"]).set_index("month")


@pytest.fixture(scope="module")
def engine(panel, macro_real) -> S.CreditRiskStressEngine:
    return S.CreditRiskStressEngine.from_data(panel, macro_real)


def _synthetic(n=160, seed=0, coefs=(0.05, 0.10, -0.03), noise=0.01):
    """Mora cuyo cambio a 12 meses sigue exactamente el modelo satelite con coeficientes conocidos."""
    rng = np.random.default_rng(seed)
    idx = _months(n)
    macro = pd.DataFrame(
        {
            "tpm_pct": np.cumsum(rng.normal(0, 0.4, n)) + 5,
            "unemployment_pct": np.cumsum(rng.normal(0, 0.2, n)) + 8,
            "imacec_yoy_pct": rng.normal(2, 3, n),
        },
        index=idx,
    )
    x = pd.DataFrame(
        {
            "a": macro["tpm_pct"].diff(12).shift(S.LAG),
            "b": macro["unemployment_pct"].diff(12).shift(S.LAG),
            "c": macro["imacec_yoy_pct"].shift(S.LAG),
        }
    ).fillna(0.0)
    d12 = 0.1 + x.to_numpy() @ np.array(coefs) + rng.normal(0, noise, n)
    # mora_t = mora_{t-12} + d12_t: se construye por bloques de 12 meses
    mora = np.full(n, 2.0)
    for t in range(12, n):
        mora[t] = mora[t - 12] + d12[t]
    return pd.Series(mora, index=idx), macro


# ------------------------------------------------------------------------------- estimacion
def test_fit_recovers_known_coefficients():
    mora, macro = _synthetic()
    fit = S.fit_satellite(mora, macro, exclude_covid=False)
    np.testing.assert_allclose(fit.params[list(S.FACTORS)].to_numpy(), [0.05, 0.10, -0.03], atol=0.01)
    assert fit.r2 > 0.95


def test_design_excludes_covid_relief_months():
    mora, macro = _synthetic()
    d = S.design(mora, macro)
    start, end = (pd.Timestamp(x) for x in S.COVID_RELIEF)
    assert not ((d.index >= start) & (d.index <= end)).any()
    assert len(S.design(mora, macro, exclude_covid=False)) > len(d)


def test_design_lags_macro_by_six_months():
    mora, macro = _synthetic()
    d = S.design(mora, macro, exclude_covid=False)
    t = d.index[10]
    assert d.at[t, "imacec_yoy_pct"] == macro["imacec_yoy_pct"].loc[t - pd.DateOffset(months=S.LAG)]


def test_fit_rejects_too_short_samples():
    mora, macro = _synthetic(n=40)
    with pytest.raises(ValueError, match="pocas observaciones"):
        S.fit_satellite(mora, macro)


def test_beta_params_match_mean_and_rejects_impossible_sd():
    a, b = S.beta_params(0.45, 0.10)
    assert a / (a + b) == pytest.approx(0.45)
    assert np.sqrt(a * b / ((a + b) ** 2 * (a + b + 1))) == pytest.approx(0.10)
    with pytest.raises(ValueError):
        S.beta_params(0.05, 0.4)


# ------------------------------------------------------------------------------- simulacion
def test_simulation_is_reproducible_and_seed_matters(engine):
    sc = S.StressScenario("x", 200, 1.0, -1.0)
    r1, r2 = engine.simulate(sc, n_sims=2000, seed=7), engine.simulate(sc, n_sims=2000, seed=7)
    r3 = engine.simulate(sc, n_sims=2000, seed=8)
    assert r1 == r2
    assert r1["mean_mora_pct"] != r3["mean_mora_pct"]


def test_percentiles_are_ordered_and_loss_is_consistent(engine):
    r = engine.simulate(S.StressScenario("x", 300, 2.0, -3.0), n_sims=5000)
    assert r["p05_mora_pct"] <= r["mean_mora_pct"] <= r["p95_mora_pct"] <= r["p99_mora_pct"]
    assert r["p95_loss_mm"] <= r["p99_loss_mm"]
    assert r["unexpected_loss_99_mm"] == pytest.approx(r["p99_loss_mm"] - r["mean_loss_mm"])
    # mora media * LGD media * EAD ~ perdida media (LGD independiente de la mora en la simulacion)
    assert r["mean_loss_mm"] == pytest.approx(r["mean_mora_pct"] / 100 * S.LGD_MEAN * r["ead_mm"], rel=0.02)


def test_a_rate_hike_raises_consumer_delinquency(engine):
    calm = engine.simulate(S.StressScenario("calma", 0, 0, 2.0), "consumo")
    hike = engine.simulate(S.StressScenario("alza", 500, 0, 2.0), "consumo")
    assert hike["mean_mora_pct"] > calm["mean_mora_pct"]


def test_loss_fields_only_for_total(engine):
    sc = S.StressScenario("x", 0, 0, 2.0)
    assert "ead_mm" in engine.simulate(sc, "total", n_sims=500)
    assert "ead_mm" not in engine.simulate(sc, "consumo", n_sims=500)


def test_flags_scenarios_outside_the_estimation_range(engine):
    assert engine.out_of_range(S.StressScenario("x", 0, 0, 2.0)) == []
    assert "imacec_yoy_pct" in engine.out_of_range(S.StressScenario("x", 0, 0, -25.0))


def test_simulate_validates_inputs(engine):
    sc = S.StressScenario("x", 0, 0, 2.0)
    with pytest.raises(KeyError):
        engine.simulate(sc, "hipotecario")
    with pytest.raises(ValueError):
        engine.simulate(sc, n_sims=10)


# ------------------------------------------------------------------------------- datos reales
def test_engine_uses_real_ead_and_latest_month(engine, panel):
    last = panel[panel["is_system"]].sort_values("date").iloc[-1]
    assert engine.as_of == f"{last['date']:%Y-%m}"
    assert engine.ead_mm == pytest.approx(last["mora90_mm"] / (last["total"] / 100))


def test_consumer_mora_responds_to_the_policy_rate(engine):
    """Hallazgo central: excluyendo el alivio COVID, la mora de consumo sube con la TPM 6 meses antes."""
    fit = engine.fits["consumo"]
    assert fit.params["d_tpm_pp"] > 0 and fit.tvalues["d_tpm_pp"] > 3


def test_historical_scenario_reads_observed_changes(macro_real):
    sc = S.historical_scenario(macro_real, "2022-12-01", "alzas")
    expected = macro_real.loc["2022-12-01", "tpm_pct"] - macro_real.loc["2021-12-01", "tpm_pct"]
    assert sc.tpm_shock_bp == pytest.approx(expected * 100)


def test_stress_grid_reports_against_the_base_scenario(engine, macro_real):
    g = S.stress_grid(macro_real, engine=engine, n_sims=1000)
    base = g[g["scenario_name"] == g["scenario_name"].iloc[0]]
    assert (base["mean_vs_base_pp"] == 0).all()
    assert len(g) == len(S.default_scenarios(macro_real)) * len(engine.fits)


def test_conditional_backtest_never_trains_on_overlapping_changes(panel, macro_real):
    mora = A.system_series(panel)["consumo"]
    b = S.conditional_backtest(mora, macro_real, start="2025-06-01")
    assert len(b) > 0
    np.testing.assert_allclose(b["err_model"], b["actual"] - b["pred"])


# ------------------------------------------------------------------------------- robustez
def test_sign_restriction_drops_a_wrong_signed_factor():
    """Si el desempleo baja la mora en los datos, el modelo de estres lo elimina en vez de usarlo."""
    mora, macro = _synthetic(coefs=(0.05, -0.10, -0.03))
    free = S.fit_satellite(mora, macro, exclude_covid=False, sign_restrict=False)
    assert free.params["d_unemployment_pp"] < 0 and free.dropped == ()
    fit = S.fit_satellite(mora, macro, exclude_covid=False)
    assert fit.dropped == ("d_unemployment_pp",)
    assert fit.params["d_unemployment_pp"] == 0 and fit.cov.loc["d_unemployment_pp"].abs().sum() == 0
    assert fit.params["d_tpm_pp"] > 0 and fit.params["imacec_yoy_pct"] < 0


def test_dropped_factors_do_not_move_the_simulation(engine):
    fit = engine.fits["consumo"]
    assert "d_unemployment_pp" in fit.dropped
    a = engine.simulate(S.StressScenario("a", 100, 0.0, 2.0), "consumo", n_sims=1000)
    b = engine.simulate(S.StressScenario("b", 100, 5.0, 2.0), "consumo", n_sims=1000)
    assert a["mean_mora_pct"] == b["mean_mora_pct"] and a["factors_dropped"] == list(fit.dropped)


def test_select_lag_recovers_the_true_lag():
    rng = np.random.default_rng(3)
    n, true_lag = 170, 9
    idx = _months(n)
    macro = pd.DataFrame({"tpm_pct": np.cumsum(rng.normal(0, 0.5, n)) + 5, "unemployment_pct": 8 + rng.normal(0, 0.1, n),
                          "imacec_yoy_pct": rng.normal(2, 0.5, n)}, index=idx)
    d12 = 0.3 * macro["tpm_pct"].diff(12).shift(true_lag).fillna(0).to_numpy() + rng.normal(0, 0.02, n)
    mora = np.full(n, 2.0)
    for t in range(12, n):
        mora[t] = mora[t - 12] + d12[t]
    assert S.select_lag(pd.Series(mora, index=idx), macro) == true_lag


def test_nested_backtest_chooses_the_lag_with_past_data_only(panel, macro_real):
    mora = A.system_series(panel)["consumo"]
    b = S.conditional_backtest(mora, macro_real, start="2025-06-01")
    assert set(b["lag"]) <= set(S.LAG_CANDIDATES)
    t = b.index[0]
    cutoff = t - pd.DateOffset(months=S.WINDOW)
    assert b.at[t, "lag"] == S.select_lag(mora.loc[:cutoff], macro_real.loc[:cutoff])


def test_lag_sensitivity_reports_every_candidate(panel, macro_real):
    out = S.lag_sensitivity(A.system_series(panel)["consumo"], macro_real, start="2026-01-01")
    assert set(out) == {f"rezago_{k}" for k in S.LAG_CANDIDATES} | {"elegido"}
    assert all(v > 0 for v in out.values())


def test_bank_sensitivity_and_cochran_q():
    mora, macro = _synthetic(coefs=(0.05, 0.0, -0.03))
    mora2, _ = _synthetic(coefs=(0.20, 0.0, -0.03))  # misma macro, otra sensibilidad
    wide = pd.DataFrame({"lento": mora, "rapido": mora2})
    table, het = S.bank_sensitivity(wide, macro, lag=S.LAG)
    assert list(table.index) == ["rapido", "lento"]
    assert table.loc["rapido", "lo"] < table.loc["rapido", "beta_tpm"] < table.loc["rapido", "hi"]
    assert het["gl"] == 1 and het["q_cochran"] > 3.84
    assert table["beta_tpm"].min() <= het["beta_combinado"] <= table["beta_tpm"].max()


# ------------------------------------------------------------------------------- estres por banco
def test_two_stage_oracle_recovers_a_bank_that_follows_the_system(panel, macro_real):
    """Un banco que es exactamente 0,5 + 2 x sistema queda sin error en la etapa 2 con el cambio real."""
    system = A.system_series(panel)["consumo"]
    noise = np.random.default_rng(1).normal(0, 0.5, len(system))
    wide = pd.DataFrame({"espejo": 0.5 + 2.0 * system, "ruido": system.mean() + noise}, index=system.index)
    summary = S.bank_backtest_summary(S.bank_conditional_backtest(wide, system, macro_real, start="2025-01-01"))
    oracle = summary[summary["mode"] == "dos_etapas_oraculo"].set_index("bank")
    assert oracle.loc["espejo", "abs_err"] < 1e-9
    assert oracle.loc["ruido", "rmae"] > oracle.loc["espejo", "rmae"]
    assert set(summary["mode"]) == set(S.BANK_MODES) and "Todos" in set(summary["bank"])


def test_bank_backtest_never_uses_the_future_of_the_bank(panel, macro_real):
    """Alterar la mora del banco despues de t-12 cambia el valor real en t, pero no la prediccion."""
    system = A.system_series(panel)["consumo"]
    base = pd.DataFrame({"b": 1.0 + 0.8 * system}, index=system.index)
    t = pd.Timestamp("2025-06-01")
    shocked = base.copy()
    shocked.loc[shocked.index > t - pd.DateOffset(months=12), "b"] += 5.0
    pick = lambda e: e[(e["date"] == t) & (e["mode"] == "dos_etapas")].iloc[0]  # noqa: E731
    a = pick(S.bank_conditional_backtest(base, system, macro_real, start="2025-06-01"))
    b = pick(S.bank_conditional_backtest(shocked, system, macro_real, start="2025-06-01"))
    assert a["pred"] == pytest.approx(b["pred"])
    assert b["actual"] == pytest.approx(a["actual"] + 5.0)
