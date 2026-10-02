"""Análisis descriptivo del panel de morosidad 90+ días.

Todo parte del panel que entrega ``parse.build_panel``. Las funciones son puras
(reciben y devuelven DataFrames) para poder probarlas con datos de juguete.
"""
from __future__ import annotations

import pandas as pd

from .parse import PORTFOLIOS, SYSTEM_NAME

REGIMES = [
    ("Pre-COVID", "2016-01", "2020-02"),
    ("Alivio COVID", "2020-03", "2021-12"),
    ("Normalización", "2022-01", None),
]


def regime_of(date: pd.Timestamp) -> str:
    for name, start, end in REGIMES:
        if date >= pd.Timestamp(start) and (end is None or date <= pd.Timestamp(end)):
            return name
    return "Fuera de rango"


def system_series(panel: pd.DataFrame, fill: bool = True) -> pd.DataFrame:
    """Serie oficial del sistema bancario, indexada por mes y sin huecos.

    En el archivo de 2023-07 la CMF publicó '---' en la fila del sistema (los 18 bancos
    sí vienen). Con ``fill=True`` ese único mes se interpola linealmente y se marca en
    la columna ``imputed``; un hueco más largo (más de 1 mes) levanta un error en vez
    de inventar datos. Con ``fill=False`` se devuelve lo publicado, con NaN.
    """
    cols = [*PORTFOLIOS, "mora90_mm"]
    s = panel[panel["bank"] == SYSTEM_NAME].set_index("date").sort_index()[cols]
    if not fill:
        return s
    s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))
    s["imputed"] = s["total"].isna()
    s[cols] = s[cols].interpolate(limit=1, limit_area="inside")
    if s["total"].isna().any():
        raise ValueError("Hay huecos de más de un mes en la serie del sistema")
    return s


def regime_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Mora media por cartera en cada régimen, más mínimo y máximo históricos."""
    s = system_series(panel).copy()
    s["regimen"] = [regime_of(d) for d in s.index]
    table = s.groupby("regimen", sort=False)[PORTFOLIOS].mean()
    table = table.loc[[r[0] for r in REGIMES]]
    extremes = pd.DataFrame(
        {
            "minimo": s[PORTFOLIOS].min(),
            "mes_minimo": s[PORTFOLIOS].idxmin().dt.strftime("%Y-%m"),
            "maximo": s[PORTFOLIOS].max(),
            "mes_maximo": s[PORTFOLIOS].idxmax().dt.strftime("%Y-%m"),
        }
    )
    return table.round(3), extremes


def implied_loans(panel: pd.DataFrame) -> pd.Series:
    """Colocaciones implícitas (MM$) = mora en MM$ / (mora % / 100).

    La CMF publica la mora en % y en MM$ pero no el saldo de colocaciones; se despeja.
    Solo existe donde la mora es positiva.
    """
    pct = panel["total"]
    loans = panel["mora90_mm"] / (pct / 100.0)
    return loans.where(pct > 0)


def kitagawa(panel: pd.DataFrame, start: str, end: str) -> dict:
    """Descompone la variación de la mora del sistema entre dos meses.

    Delta = dentro de cada banco (cambia su mora) + mezcla (cambia su peso en la cartera).
    Se usa solo el conjunto de bancos que existen en ambos meses; se informa qué
    fracción de las colocaciones cubre ese conjunto.
    """
    p = panel[~panel["is_system"]].copy()
    p["loans"] = implied_loans(p)
    a = p[p["date"] == pd.Timestamp(start)].set_index("bank")
    b = p[p["date"] == pd.Timestamp(end)].set_index("bank")
    common = a.index.intersection(b.index)
    common = [x for x in common if pd.notna(a.at[x, "loans"]) and pd.notna(b.at[x, "loans"])]
    if not common:
        raise ValueError("No hay bancos con colocaciones implícitas en ambos meses")
    a_c, b_c = a.loc[common], b.loc[common]
    w0 = a_c["loans"] / a_c["loans"].sum()
    w1 = b_c["loans"] / b_c["loans"].sum()
    m0, m1 = a_c["total"], b_c["total"]
    within = float((((w0 + w1) / 2) * (m1 - m0)).sum())
    mix = float((((m0 + m1) / 2) * (w1 - w0)).sum())
    total = float((w1 * m1).sum() - (w0 * m0).sum())
    return {
        "inicio": start,
        "fin": end,
        "mora_inicio": float((w0 * m0).sum()),
        "mora_fin": float((w1 * m1).sum()),
        "variacion_pp": total,
        "dentro_bancos_pp": within,
        "mezcla_pp": mix,
        "residuo": total - within - mix,
        "bancos_comunes": len(common),
        "cobertura_colocaciones_inicio": float(a_c["loans"].sum() / a["loans"].sum()),
        "cobertura_colocaciones_fin": float(b_c["loans"].sum() / b["loans"].sum()),
    }


def bank_contributions(panel: pd.DataFrame, start: str, end: str, top: int = 8) -> pd.DataFrame:
    """Aporte de cada banco al alza de la mora del sistema (parte 'dentro' + 'mezcla')."""
    p = panel[~panel["is_system"]].copy()
    p["loans"] = implied_loans(p)
    a = p[p["date"] == pd.Timestamp(start)].set_index("bank")
    b = p[p["date"] == pd.Timestamp(end)].set_index("bank")
    common = [x for x in a.index.intersection(b.index) if pd.notna(a.at[x, "loans"]) and pd.notna(b.at[x, "loans"])]
    a_c, b_c = a.loc[common], b.loc[common]
    w0 = a_c["loans"] / a_c["loans"].sum()
    w1 = b_c["loans"] / b_c["loans"].sum()
    out = pd.DataFrame(
        {
            "peso_inicio": w0,
            "peso_fin": w1,
            "mora_inicio": a_c["total"],
            "mora_fin": b_c["total"],
            "aporte_pp": (w1 * b_c["total"]) - (w0 * a_c["total"]),
        }
    )
    return out.sort_values("aporte_pp", ascending=False).head(top).round(4)


def dispersion(panel: pd.DataFrame, portfolio: str = "consumo") -> pd.DataFrame:
    """Percentiles de mora entre bancos para una cartera, mes a mes."""
    p = panel[~panel["is_system"]]
    g = p.groupby("date")[portfolio]
    out = pd.DataFrame(
        {
            "n_bancos": g.count(),
            "p25": g.quantile(0.25),
            "mediana": g.median(),
            "p75": g.quantile(0.75),
        }
    )
    out["iqr"] = out["p75"] - out["p25"]
    return out


def bank_changes(panel: pd.DataFrame, portfolio: str = "consumo", months: int = 12) -> pd.DataFrame:
    """Variación de la mora de cada banco en el último año, ordenada de mayor a menor."""
    p = panel[~panel["is_system"]]
    last = p["date"].max()
    prev = last - pd.DateOffset(months=months)
    now = p[p["date"] == last].set_index("bank")[portfolio]
    before = p[p["date"] == prev].set_index("bank")[portfolio]
    out = pd.DataFrame({"antes": before, "ahora": now}).dropna()
    out["cambio_pp"] = out["ahora"] - out["antes"]
    return out.sort_values("cambio_pp", ascending=False).round(3)


def rank_persistence(panel: pd.DataFrame, portfolio: str, date_a: str, date_b: str) -> float:
    """Correlación de rangos (Spearman) de la mora entre bancos en dos fechas."""
    p = panel[~panel["is_system"]]
    a = p[p["date"] == pd.Timestamp(date_a)].set_index("bank")[portfolio]
    b = p[p["date"] == pd.Timestamp(date_b)].set_index("bank")[portfolio]
    both = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(both) < 4:
        return float("nan")
    return float(both["a"].rank().corr(both["b"].rank()))


def covid_swing(panel: pd.DataFrame) -> dict:
    """Caída desde el último mes pre-COVID hasta el mínimo y rebote posterior."""
    s = system_series(panel)["total"]
    pre = s.loc["2020-02-01"]
    trough_date = s.loc["2020-03-01":].idxmin()
    trough = s.loc[trough_date]
    last = s.iloc[-1]
    return {
        "mora_feb_2020": float(pre),
        "minimo_post_covid": float(trough),
        "mes_minimo": trough_date.strftime("%Y-%m"),
        "ultimo": float(last),
        "ultimo_mes": s.index[-1].strftime("%Y-%m"),
        "caida_pp": float(trough - pre),
        "rebote_pp": float(last - trough),
        "ultimo_vs_pre_covid_pp": float(last - pre),
    }
