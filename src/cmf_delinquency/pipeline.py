"""Pipeline completo: descarga -> panel -> análisis -> backtest -> figuras -> results.json.

Uso:
    python -m cmf_delinquency.pipeline            # descarga lo que falte y corre todo
    python -m cmf_delinquency.pipeline --offline  # usa data/panel_mora90.csv ya versionado
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import analysis as A
from . import forecast as F
from . import plots
from .download import download_all
from .parse import build_panel

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PANEL_CSV = ROOT / "data" / "panel_mora90.csv"
FIGS = ROOT / "reports" / "figures"
RESULTS = ROOT / "reports" / "results.json"
TABLES = ROOT / "reports" / "tables"

TROUGH = "2021-12-01"
PRE_COVID = "2019-12-01"


def load_panel(offline: bool) -> pd.DataFrame:
    if offline:
        return pd.read_csv(PANEL_CSV, parse_dates=["date"])
    download_all(RAW)
    panel = build_panel(RAW)
    PANEL_CSV.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_CSV, index=False)
    return panel


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def run(offline: bool = False) -> dict:
    panel = load_panel(offline)
    last_month = panel["date"].max()
    end = f"{last_month:%Y-%m-01}"
    TABLES.mkdir(parents=True, exist_ok=True)

    regimes, extremes = A.regime_table(panel)
    regimes.to_csv(TABLES / "regimes.csv")
    swing = A.covid_swing(panel)
    since_trough = A.kitagawa(panel, TROUGH, end)
    since_pre = A.kitagawa(panel, PRE_COVID, end)
    contrib = A.bank_contributions(panel, TROUGH, end, top=12)
    contrib.to_csv(TABLES / "contributions_since_trough.csv")
    disp = A.dispersion(panel, "consumo")
    changes = A.bank_changes(panel, "consumo", 12)
    changes.to_csv(TABLES / "consumo_change_12m.csv")
    persistence = A.rank_persistence(panel, "consumo", PRE_COVID, end)

    series = A.system_series(panel)["total"]
    errors = F.rolling_origin(series)
    rel = F.relative_mae(errors, ["h"])
    rel.to_csv(TABLES / "forecast_rmae.csv")
    ci_rows = []
    for model in ("arima_111", "ets_damped", "drift"):
        for h in F.HORIZONS:
            point, lo, hi = F.rmae_ci(errors, model, h)
            ci_rows.append({"model": model, "h": h, "rmae": point, "lo": lo, "hi": hi})
    ci = pd.DataFrame(ci_rows)
    ci.to_csv(TABLES / "forecast_rmae_ci.csv", index=False)

    plots.fig_system(panel, FIGS / "01_mora_sistema.png")
    plots.fig_contributions(
        contrib.head(11), FIGS / "02_aporte_bancos.png",
        f"Quién explica el alza de mora desde {TROUGH[:7]} hasta {end[:7]}",
    )
    plots.fig_dispersion(panel, FIGS / "03_dispersion_consumo.png", "consumo")
    plots.fig_forecast(ci, FIGS / "04_backtest_rmae.png")
    plots.fig_heatmap(panel, FIGS / "05_mapa_calor_bancos.png")

    peak = disp["iqr"].idxmax()
    results = {
        "datos": {
            "meses": int(panel["date"].nunique()),
            "desde": f"{panel['date'].min():%Y-%m}",
            "hasta": f"{last_month:%Y-%m}",
            "filas": int(len(panel)),
            "entidades": int(panel.loc[~panel["is_system"], "bank"].nunique()),
        },
        "regimenes_mora_media": regimes.to_dict(orient="index"),
        "extremos": extremes.to_dict(orient="index"),
        "covid": swing,
        "descomposicion_desde_minimo": since_trough,
        "descomposicion_desde_pre_covid": since_pre,
        "mayor_aporte": contrib.head(3)["aporte_pp"].to_dict(),
        "dispersion_consumo": {
            "mes_max_iqr": f"{peak:%Y-%m}",
            "iqr_max": float(disp["iqr"].max()),
            "iqr_ultimo": float(disp["iqr"].iloc[-1]),
        },
        "persistencia_rangos_consumo": persistence,
        "backtest": {
            "origenes_h1": int(rel.loc[1, "n"]),
            "rmae": rel[list(F.MODELS)].to_dict(orient="index"),
            "ic95": ci.to_dict(orient="records"),
        },
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(_round(results), indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="usar el panel ya versionado, sin descargar")
    args = ap.parse_args()
    res = run(offline=args.offline)
    d = res["datos"]
    print(f"Panel: {d['filas']} filas, {d['entidades']} entidades, {d['desde']} -> {d['hasta']}")
    print(f"Resultados en {RESULTS}")


if __name__ == "__main__":
    main()
