"""Pronostico de la mora por banco, con modelos que toman informacion entre bancos.

Cada banco tiene pocas observaciones y es ruidoso, asi que un modelo por banco tiene poco que
aprender. La alternativa es un modelo agrupado: una sola regresion sobre todos los bancos, cuyas
features incluyen la brecha del banco respecto del sistema (si un banco esta muy por sobre el
sistema, tiende a volver?) y el momentum del sistema.

El protocolo es el mismo que para el sistema: origen movil, solo se entrena con pares cuyo
desenlace ya se conocia en el origen, y se compara contra el pronostico ingenuo.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .analysis import implied_loans, regime_of
from .forecast import HORIZONS, MIN_TRAIN

POOLED_MODELS = {
    "pooled_momentum": ["mom3"],
    "pooled_gap": ["mom3", "gap"],
    "pooled_system": ["mom3", "gap", "sys_mom3"],
}
ALL_MODELS = ("naive", "ets_damped", *POOLED_MODELS)
MIN_POOLED_ROWS = 60


def eligible_banks(panel: pd.DataFrame, portfolio: str = "total", min_months: int = 100, min_share: float = 0.01) -> list[str]:
    """Bancos con historia suficiente y tamano relevante.

    ``min_share`` es la participacion mediana en las colocaciones implicitas del sistema: deja fuera
    sucursales de bancos extranjeros y bancos muy chicos, cuya mora salta de 0% a 4% con un solo
    credito y dominaria cualquier promedio de errores.
    """
    p = panel[~panel["is_system"]].copy()
    p["loans"] = implied_loans(p)
    share = p.assign(total_loans=p.groupby("date")["loans"].transform("sum"))
    share["share"] = share["loans"] / share["total_loans"]
    median_share = share.groupby("bank")["share"].median()
    months = p.groupby("bank")[portfolio].count()
    keep = months[months >= min_months].index.intersection(median_share[median_share >= min_share].index)
    return sorted(keep)


def wide_series(panel: pd.DataFrame, banks: list[str], portfolio: str = "total") -> pd.DataFrame:
    """Mes x banco, sin huecos interiores de un solo mes (se interpolan)."""
    p = panel[(~panel["is_system"]) & panel["bank"].isin(banks)]
    wide = p.pivot(index="date", columns="bank", values=portfolio).sort_index()
    wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="MS"))
    return wide.interpolate(limit=1, limit_area="inside")


def pooled_features(wide: pd.DataFrame, system: pd.Series) -> dict[str, pd.DataFrame]:
    """Features conocidas en cada mes ``t`` para cada banco."""
    sys_aligned = system.reindex(wide.index)
    return {
        "mom3": wide - wide.shift(3),
        "gap": wide.sub(sys_aligned, axis=0),
        "sys_mom3": pd.DataFrame({b: sys_aligned - sys_aligned.shift(3) for b in wide.columns}),
    }


def _ols_fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return beta


def _ets_forecasts(history: np.ndarray, horizons) -> dict[int, float] | None:
    if len(history) < 24:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fit = ExponentialSmoothing(history, trend="add", damped_trend=True, initialization_method="estimated").fit()
            path = fit.forecast(max(horizons))
        except Exception:  # noqa: BLE001 - un banco con serie degenerada no debe tumbar todo el backtest
            return None
    return {h: float(path[h - 1]) for h in horizons}


def pooled_rolling_origin(
    wide: pd.DataFrame, system: pd.Series, horizons=HORIZONS, min_train: int = MIN_TRAIN
) -> pd.DataFrame:
    """Errores por (banco, origen, horizonte, modelo) para el pronostico agrupado y sus referencias."""
    feats = {k: v.to_numpy() for k, v in pooled_features(wide, system).items()}
    values = wide.to_numpy()
    n, n_banks = values.shape
    banks = list(wide.columns)
    rows = []
    for origin in range(min_train, n):
        o = origin - 1
        ets_cache = {b: _ets_forecasts(values[: o + 1, j][~np.isnan(values[: o + 1, j])], horizons) for j, b in enumerate(banks)}
        for h in horizons:
            target_pos = o + h
            if target_pos >= n:
                continue
            fitted = {}
            for name, cols in POOLED_MODELS.items():
                xs, ys = [], []
                for s in range(0, o - h + 1):
                    x = np.column_stack([feats[c][s] for c in cols])  # (bancos, features)
                    y = values[s + h] - values[s]
                    ok = ~np.isnan(x).any(axis=1) & ~np.isnan(y)
                    xs.append(x[ok])
                    ys.append(y[ok])
                x_train, y_train = np.vstack(xs), np.concatenate(ys)
                if len(y_train) >= MIN_POOLED_ROWS:
                    fitted[name] = (cols, _ols_fit(x_train, y_train))
            for j, bank in enumerate(banks):
                actual = values[target_pos, j]
                last = values[o, j]
                if np.isnan(actual) or np.isnan(last):
                    continue
                preds = {"naive": last}
                ets = ets_cache[bank]
                if ets is not None:
                    preds["ets_damped"] = ets[h]
                for name, (cols, beta) in fitted.items():
                    x_new = np.array([feats[c][o, j] for c in cols])
                    if not np.isnan(x_new).any():
                        preds[name] = float(last + beta[0] + x_new @ beta[1:])
                for name, pred in preds.items():
                    rows.append({
                        "bank": bank, "origin": wide.index[o], "target": wide.index[target_pos], "h": h, "model": name,
                        "pred": pred, "actual": float(actual), "abs_err": abs(pred - float(actual)),
                        "regime": regime_of(wide.index[target_pos]),
                    })
    return pd.DataFrame(rows)


def common_support(errors: pd.DataFrame) -> pd.DataFrame:
    """Solo los (banco, origen, horizonte) donde existen TODOS los modelos, para comparar lo mismo."""
    needed = errors["model"].nunique()
    full = errors.groupby(["bank", "origin", "h"])["model"].nunique()
    keys = full[full == needed].reset_index()[["bank", "origin", "h"]]
    return errors.merge(keys, on=["bank", "origin", "h"])


def per_origin(errors: pd.DataFrame) -> pd.DataFrame:
    """Error absoluto medio entre bancos para cada (origen, horizonte, modelo).

    Es la unidad correcta para el bootstrap: los bancos de un mismo mes comparten el shock del mes,
    asi que el remuestreo se hace por origen y no por banco.
    """
    return errors.groupby(["origin", "h", "model"], as_index=False)["abs_err"].mean()


def bank_table(errors: pd.DataFrame, model: str, h: int) -> pd.DataFrame:
    """MAE de ``model`` relativo al ingenuo, banco por banco, a un horizonte."""
    sub = errors[errors["h"] == h]
    mae = sub.groupby(["bank", "model"])["abs_err"].mean().unstack("model")
    out = pd.DataFrame({
        "mae_naive_pp": mae["naive"], f"mae_{model}_pp": mae[model], "rmae": mae[model] / mae["naive"],
        "n_origenes": sub[sub["model"] == "naive"].groupby("bank").size(),
    })
    return out.sort_values("rmae")
