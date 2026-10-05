"""Genera la pagina de GitHub Pages (``docs/index.html``) a partir del panel y de ``results.json``.

La pagina es un solo HTML con los datos incrustados: no hay servidor ni dependencias externas.
Todo numero que muestra sale de los archivos del repo, asi que no puede desincronizarse del
README ni de las tablas.

    python -m cmf_delinquency.site
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pandas as pd

from . import analysis as A

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("site_template.html")
PANEL_CSV = ROOT / "data" / "panel_mora90.csv"
RESULTS_JSON = ROOT / "reports" / "results.json"
FIGURES_DIR = ROOT / "reports" / "figures"
DOCS_DIR = ROOT / "docs"

PORTFOLIOS = ["total", "comercial", "consumo", "vivienda", "personas"]
DEFAULT_BANK = "Banco Santander-Chile"
MIN_MONTHS_FOR_EXPLORER = 12


def _clean(values) -> list[float | None]:
    """Lista JSON: NaN -> null y 3 decimales (alcanza para porcentajes de mora)."""
    return [None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), 3) for v in values]


def _r2(row: dict) -> dict:
    """Redondea a 2 decimales en Python. JavaScript y Python desempatan distinto (1,305 -> 1,31 contra 1,30);
    al redondear aqui, la pagina muestra exactamente las mismas cifras que el README."""
    return {k: (round(v, 2) if isinstance(v, float) and math.isfinite(v) else v) for k, v in row.items()}


def _regimes(months: list[str]) -> list[dict]:
    index = {m: i for i, m in enumerate(months)}
    last = len(months) - 1
    return [
        {"key": "reg_pre", "i0": 0, "i1": index["2020-02"]},
        {"key": "reg_covid", "i0": index["2020-03"], "i1": index["2021-12"]},
        {"key": "reg_norm", "i0": index["2022-01"], "i1": last},
    ]


def _swing(series: pd.Series) -> float:
    """Caida de una cartera entre febrero de 2020 y su minimo posterior."""
    trough = series.loc["2020-03-01":].min()
    return float(trough - series.loc["2020-02-01"])


def build_data(panel: pd.DataFrame, results: dict) -> dict:
    system = A.system_series(panel)
    months = [f"{d:%Y-%m}" for d in system.index]

    banks = {}
    entities = panel[~panel["is_system"]]
    for bank, g in entities.groupby("bank"):
        if g["total"].count() < MIN_MONTHS_FOR_EXPLORER:
            continue
        wide = g.set_index("date").reindex(system.index)
        banks[bank] = {p: _clean(wide[p]) for p in PORTFOLIOS}

    covid = results["covid"]
    decomposition = results["descomposicion_desde_minimo"]
    system_rows = [
        {"model": r["model"], "h": r["h"], "rmae": r["rmae"], "rmae_lo": r["lo"], "rmae_hi": r["hi"]}
        for r in results["backtest"]["ic95"]
    ]
    system_rows = [_r2(r) for r in system_rows]
    macro_rows = [_r2(r) for r in results["macro"]["backtest"] if r["model"] in ("momentum+unemployment", "momentum+macro")]
    bank_rows = [_r2(r) for r in results["bancos_pronostico"]["backtest"] if r["model"] in ("ets_damped", "pooled_gap", "pooled_system")]

    return {
        "months": months,
        "regimes": _regimes(months),
        "imputed_idx": [i for i, flag in enumerate(system["imputed"]) if flag],
        "system": {p: _clean(system[p]) for p in PORTFOLIOS},
        "banks": banks,
        "bank_names": sorted(banks),
        "default_bank": DEFAULT_BANK if DEFAULT_BANK in banks else sorted(banks)[0],
        "key": {
            **_r2({
                "feb2020": covid["mora_feb_2020"], "min": covid["minimo_post_covid"], "last": covid["ultimo"],
                "fall_comercial": _swing(system["comercial"]), "fall_vivienda": _swing(system["vivienda"]),
                "rise": decomposition["variacion_pp"], "within": decomposition["dentro_bancos_pp"], "mix": decomposition["mezcla_pp"],
            }),
            "last_month": covid["ultimo_mes"],
        },
        "forecast": {"system": system_rows, "macro": macro_rows, "banks": bank_rows},
        "fill": {"n": results["backtest"]["origenes_h1"], "nb": len(results["bancos_pronostico"]["bancos"])},
    }


def render(data: dict) -> str:
    payload = json.dumps(data, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # un "</script>" dentro de un dato cerraria la etiqueta
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)


def build_site(docs_dir: Path = DOCS_DIR, panel_csv: Path = PANEL_CSV, results_json: Path = RESULTS_JSON,
               figures_dir: Path = FIGURES_DIR) -> Path:
    panel = pd.read_csv(panel_csv, parse_dates=["date"])
    results = json.loads(results_json.read_text(encoding="utf-8"))
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "index.html"
    out.write_text(render(build_data(panel, results)), encoding="utf-8")
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")
    target = docs_dir / "figures"
    target.mkdir(exist_ok=True)
    for png in figures_dir.glob("*.png"):
        shutil.copy2(png, target / png.name)
    return out


if __name__ == "__main__":
    path = build_site()
    print(f"{path} ({path.stat().st_size / 1024:.0f} KB)")
