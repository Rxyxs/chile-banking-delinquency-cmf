"""Indicadores macroeconomicos mensuales para contrastar con la mora bancaria.

Fuente: https://mindicador.cl (API abierta, sin clave) que replica series del Banco Central de
Chile y del INE. Es un agregador de terceros, no el publicador oficial: las cifras pueden diferir
de las oficiales o revisarse despues. Se usan tres series con historia completa 2015-2026:

* ``unemployment_pct`` : tasa de desempleo (INE, trimestre movil), mensual.
* ``tpm_pct``          : tasa de politica monetaria, valor de fin de mes.
* ``imacec_yoy_pct``   : IMACEC, variacion anual (%).

El IPC se excluye a proposito: la API lo entrega solo hasta 2025-12.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

API = "https://mindicador.cl/api/{code}/{year}"
INDICATORS = {
    "tasa_desempleo": "unemployment_pct",
    "tpm": "tpm_pct",
    "imacec": "imacec_yoy_pct",
}
FIRST_YEAR = 2015
# El dato del mes t de desempleo e IMACEC se conoce recien en t+1; la TPM se conoce el mismo mes.
PUBLICATION_LAG_MONTHS = {"unemployment_pct": 1, "tpm_pct": 0, "imacec_yoy_pct": 1}


def _fetch_year(code: str, year: int, session: requests.Session) -> list[dict]:
    resp = session.get(API.format(code=code, year=year), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.json().get("serie", [])


def download_macro(last_year: int | None = None, delay: float = 0.2) -> pd.DataFrame:
    """Descarga las series y las deja en una tabla mensual (una fila por mes)."""
    last_year = last_year or date.today().year
    session = requests.Session()
    frames = []
    for code, name in INDICATORS.items():
        rows = []
        for year in range(FIRST_YEAR, last_year + 1):
            for obs in _fetch_year(code, year, session):
                rows.append({"date": pd.Timestamp(obs["fecha"]).tz_localize(None).normalize(), "value": obs["valor"]})
            time.sleep(delay)
        frames.append(monthly_series(pd.DataFrame(rows), name))
    return pd.concat(frames, axis=1).sort_index().rename_axis("month")


def monthly_series(raw: pd.DataFrame, name: str) -> pd.Series:
    """Una observacion por mes: la ultima del mes (para series diarias es el valor de fin de mes)."""
    raw = raw.sort_values("date").copy()
    raw["month"] = raw["date"].dt.to_period("M").dt.to_timestamp()
    return raw.groupby("month")["value"].last().rename(name)


def apply_publication_lag(macro: pd.DataFrame) -> pd.DataFrame:
    """Desplaza cada serie segun cuando se publica, para que la fila ``t`` solo traiga lo conocido en ``t``."""
    out = macro.copy()
    for col, lag in PUBLICATION_LAG_MONTHS.items():
        if col in out and lag:
            out[col] = out[col].shift(lag)
    return out


def complete_months(macro: pd.DataFrame) -> pd.DataFrame:
    """Solo los meses con las tres series presentes."""
    return macro.dropna(how="any")


if __name__ == "__main__":
    out = download_macro()
    Path("data").mkdir(exist_ok=True)
    out.to_csv("data/macro_indicators.csv")
    print(f"{len(out)} meses | {out.index.min():%Y-%m} -> {out.index.max():%Y-%m} | columnas {list(out.columns)}")
    print(out.isna().sum().to_dict())
