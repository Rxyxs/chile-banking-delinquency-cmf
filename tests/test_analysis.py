"""Chequeos de integridad sobre el panel real y de lógica sobre datos de juguete."""
import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import analysis as A
from cmf_delinquency.parse import PORTFOLIOS, SYSTEM_NAME


# ---------- integridad del panel real ----------
def test_panel_covers_every_month(panel):
    months = pd.date_range(panel["date"].min(), panel["date"].max(), freq="MS")
    assert set(months) == set(panel["date"].unique())
    assert len(months) == 128


def test_panel_has_no_duplicates(panel):
    assert not panel.duplicated(["date", "bank"]).any()


def test_panel_covers_the_three_cmf_layouts(panel):
    assert set(panel["layout"]) == {"antiguo", "nuevo"}
    assert panel.loc[panel["date"] == "2021-12-01", "layout"].eq("antiguo").all()
    assert panel.loc[panel["date"] == "2022-01-01", "layout"].eq("nuevo").all()


def test_percentages_are_plausible(panel):
    vals = panel[PORTFOLIOS].stack()
    assert vals.min() >= 0
    assert vals.max() < 100


def test_every_month_has_enough_banks(panel):
    banks_per_month = panel[~panel["is_system"]].groupby("date").size()
    assert banks_per_month.min() >= 14


def test_system_series_is_continuous_across_the_format_change(panel):
    """Si el cambio de formato de 2022 rompiera la definición, aquí saltaría la serie."""
    s = A.system_series(panel)["total"]
    assert abs(s["2022-01-01"] - s["2021-12-01"]) < 0.1


def test_only_2023_07_is_missing_in_the_published_system_row(panel):
    raw = A.system_series(panel, fill=False)
    assert list(raw.index[raw["total"].isna()]) == [pd.Timestamp("2023-07-01")]


def test_filled_series_has_no_gaps_and_flags_the_imputed_month(panel):
    s = A.system_series(panel)
    assert not s["total"].isna().any()
    assert list(s.index[s["imputed"]]) == [pd.Timestamp("2023-07-01")]
    june, july, aug = (s.loc[f"2023-0{m}-01", "total"] for m in (6, 7, 8))
    assert july == pytest.approx((june + aug) / 2)


def test_implied_system_loans_have_a_realistic_magnitude(panel):
    last = panel[(panel["date"] == panel["date"].max()) & panel["is_system"]]
    loans_mm = A.implied_loans(last).iloc[0]
    assert 1e8 < loans_mm < 5e8  # 100 a 500 billones de pesos


def test_system_pct_is_close_to_the_loan_weighted_bank_average(panel):
    d = panel[(panel["date"] == "2026-08-01") & ~panel["is_system"]].copy()
    d["loans"] = A.implied_loans(d)
    d = d.dropna(subset=["loans"])
    weighted = (d["loans"] * d["total"]).sum() / d["loans"].sum()
    official = A.system_series(panel).loc["2026-08-01", "total"]
    assert weighted == pytest.approx(official, abs=0.1)


# ---------- regímenes ----------
def test_regime_boundaries():
    assert A.regime_of(pd.Timestamp("2020-02-01")) == "Pre-COVID"
    assert A.regime_of(pd.Timestamp("2020-03-01")) == "Alivio COVID"
    assert A.regime_of(pd.Timestamp("2021-12-01")) == "Alivio COVID"
    assert A.regime_of(pd.Timestamp("2022-01-01")) == "Normalización"


def test_covid_relief_lowered_arrears_then_they_rebounded(panel):
    table, _ = A.regime_table(panel)
    assert table.loc["Alivio COVID", "total"] < table.loc["Pre-COVID", "total"]
    assert table.loc["Normalización", "total"] > table.loc["Alivio COVID", "total"]


# ---------- descomposición ----------
def _toy_panel() -> pd.DataFrame:
    rows = []
    for date, specs in (
        ("2020-01-01", {"A": (1.0, 100.0), "B": (3.0, 100.0)}),
        ("2021-01-01", {"A": (2.0, 300.0), "B": (3.0, 100.0)}),
    ):
        for bank, (pct, loans) in specs.items():
            rows.append(
                {"date": pd.Timestamp(date), "bank": bank, "is_system": False, "total": pct,
                 "mora90_mm": pct / 100 * loans}
            )
    return pd.DataFrame(rows)


def test_kitagawa_is_an_exact_identity():
    out = A.kitagawa(_toy_panel(), "2020-01-01", "2021-01-01")
    assert out["variacion_pp"] == pytest.approx(out["dentro_bancos_pp"] + out["mezcla_pp"])
    assert abs(out["residuo"]) < 1e-12


def test_kitagawa_hand_computed_example():
    # t0: pesos 50/50, mora 1 y 3 -> 2.0.  t1: pesos 75/25, mora 2 y 3 -> 2.25.
    out = A.kitagawa(_toy_panel(), "2020-01-01", "2021-01-01")
    assert out["mora_inicio"] == pytest.approx(2.0)
    assert out["mora_fin"] == pytest.approx(2.25)
    assert out["dentro_bancos_pp"] == pytest.approx(0.625 * 1.0 + 0.375 * 0.0)
    assert out["mezcla_pp"] == pytest.approx(1.5 * 0.25 + 3.0 * -0.25)


def test_kitagawa_real_panel_identity_and_coverage(panel):
    out = A.kitagawa(panel, "2021-12-01", "2026-08-01")
    assert abs(out["residuo"]) < 1e-9
    assert out["cobertura_colocaciones_fin"] > 0.9
    assert out["variacion_pp"] > 0


def test_kitagawa_needs_banks_in_both_months():
    p = _toy_panel()
    p = p[~((p["bank"] == "A") & (p["date"] == "2021-01-01"))]
    p = p[~((p["bank"] == "B") & (p["date"] == "2020-01-01"))]
    with pytest.raises(ValueError):
        A.kitagawa(p, "2020-01-01", "2021-01-01")


def test_bank_contributions_sum_to_the_change():
    contrib = A.bank_contributions(_toy_panel(), "2020-01-01", "2021-01-01", top=10)
    out = A.kitagawa(_toy_panel(), "2020-01-01", "2021-01-01")
    assert contrib["aporte_pp"].sum() == pytest.approx(out["variacion_pp"], abs=1e-3)


# ---------- dispersión y persistencia ----------
def test_dispersion_percentiles():
    p = pd.DataFrame(
        {"date": pd.Timestamp("2020-01-01"), "bank": list("ABCDE"), "is_system": False,
         "consumo": [1.0, 2.0, 3.0, 4.0, 5.0]}
    )
    d = A.dispersion(p, "consumo").iloc[0]
    assert (d["p25"], d["mediana"], d["p75"], d["iqr"], d["n_bancos"]) == (2.0, 3.0, 4.0, 2.0, 5)


def test_rank_persistence_is_one_when_order_is_preserved():
    rows = []
    for date, shift in (("2020-01-01", 0.0), ("2021-01-01", 5.0)):
        for i, bank in enumerate("ABCDE"):
            rows.append({"date": pd.Timestamp(date), "bank": bank, "is_system": False, "consumo": i + shift})
    assert A.rank_persistence(pd.DataFrame(rows), "consumo", "2020-01-01", "2021-01-01") == pytest.approx(1.0)


def test_rank_persistence_is_minus_one_when_order_reverses():
    rows = []
    for date, vals in (("2020-01-01", [1, 2, 3, 4, 5]), ("2021-01-01", [5, 4, 3, 2, 1])):
        for bank, v in zip("ABCDE", vals):
            rows.append({"date": pd.Timestamp(date), "bank": bank, "is_system": False, "consumo": float(v)})
    assert A.rank_persistence(pd.DataFrame(rows), "consumo", "2020-01-01", "2021-01-01") == pytest.approx(-1.0)


def test_rank_persistence_with_too_few_banks_is_nan():
    p = pd.DataFrame({"date": [pd.Timestamp("2020-01-01")] * 2 + [pd.Timestamp("2021-01-01")] * 2,
                      "bank": list("AB") * 2, "is_system": False, "consumo": [1.0, 2.0, 2.0, 1.0]})
    assert np.isnan(A.rank_persistence(p, "consumo", "2020-01-01", "2021-01-01"))


def test_system_name_constant_matches_the_panel(panel):
    assert SYSTEM_NAME in set(panel["bank"])
