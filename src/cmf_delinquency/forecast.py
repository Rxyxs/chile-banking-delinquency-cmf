"""Backtest de pronóstico de la mora del sistema con origen móvil.

Se comparan modelos simples contra el pronóstico ingenuo (último valor). La métrica
es el MAE relativo al ingenuo, en el mismo conjunto de orígenes y horizonte:
``rMAE < 1`` significa que el modelo le gana al ingenuo.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .analysis import regime_of

HORIZONS = (1, 3, 6, 12)
MIN_TRAIN = 60  # 5 años de historia antes del primer origen
MODELS = ("naive", "drift", "seasonal_naive", "ets_damped", "arima_111")


def forecast_naive(train: pd.Series, h: int) -> float:
    return float(train.iloc[-1])


def forecast_drift(train: pd.Series, h: int, window: int = 24) -> float:
    tail = train.iloc[-window:]
    slope = (tail.iloc[-1] - tail.iloc[0]) / (len(tail) - 1)
    return float(train.iloc[-1] + slope * h)


def forecast_seasonal_naive(train: pd.Series, h: int) -> float:
    return float(train.iloc[-12 + ((h - 1) % 12)])


def forecast_ets(train: pd.Series, h: int) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(
            train.values, trend="add", damped_trend=True, initialization_method="estimated"
        ).fit()
        return float(fit.forecast(h)[-1])


def forecast_arima(train: pd.Series, h: int) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ARIMA(train.values, order=(1, 1, 1)).fit()
        return float(fit.forecast(h)[-1])


FORECASTERS = {
    "naive": forecast_naive,
    "drift": forecast_drift,
    "seasonal_naive": forecast_seasonal_naive,
    "ets_damped": forecast_ets,
    "arima_111": forecast_arima,
}


def rolling_origin(series: pd.Series, horizons=HORIZONS, min_train: int = MIN_TRAIN) -> pd.DataFrame:
    """Errores de pronóstico para cada (origen, horizonte, modelo)."""
    series = series.dropna().sort_index()
    rows = []
    n = len(series)
    for origin in range(min_train, n):
        train = series.iloc[:origin]
        for h in horizons:
            target_pos = origin - 1 + h
            if target_pos >= n:
                continue
            actual = float(series.iloc[target_pos])
            target_date = series.index[target_pos]
            for name, fn in FORECASTERS.items():
                pred = fn(train, h)
                rows.append(
                    {
                        "origin": series.index[origin - 1],
                        "target": target_date,
                        "h": h,
                        "model": name,
                        "pred": pred,
                        "actual": actual,
                        "abs_err": abs(pred - actual),
                        "regime": regime_of(target_date),
                    }
                )
    return pd.DataFrame(rows)


def relative_mae(errors: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """MAE de cada modelo dividido por el MAE del ingenuo, agrupado por ``by``."""
    mae = errors.groupby([*by, "model"])["abs_err"].mean().unstack("model")
    rel = mae.div(mae["naive"], axis=0)
    rel["n"] = errors[errors["model"] == "naive"].groupby(by).size()
    rel["mae_naive_pp"] = mae["naive"]
    return rel.round(3)


def best_model_per_horizon(rel: pd.DataFrame) -> pd.Series:
    cols = [m for m in MODELS if m in rel.columns]
    return rel[cols].idxmin(axis=1)


def rmae_ci(
    errors: pd.DataFrame, model: str, h: int, n_boot: int = 4000, seed: int = 0, baseline: str = "naive"
) -> tuple[float, float, float]:
    """rMAE de model vs un baseline (por defecto el ingenuo) con IC 95% por bootstrap de bloques.

    Los errores de orígenes consecutivos se solapan (comparten el mismo tramo de
    historia), así que se remuestrean bloques de largo max(h, 3) y no puntos sueltos.
    """
    sub = errors[errors["h"] == h].sort_values("origin")
    e_m = sub[sub["model"] == model]["abs_err"].to_numpy()
    e_n = sub[sub["model"] == baseline]["abs_err"].to_numpy()
    n = len(e_m)
    if n < 10 or n != len(e_n):
        return float("nan"), float("nan"), float("nan")
    block = max(h, 3)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts_max = n - block
    ratios = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, starts_max + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        ratios[b] = e_m[idx].mean() / e_n[idx].mean()
    point = float(e_m.mean() / e_n.mean())
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return point, float(lo), float(hi)


# --------------------------------------------------------------------------- con indicadores macro
DIRECT_MODELS = {
    "momentum": ["momentum_3m"],
    "momentum+unemployment": ["momentum_3m", "d6_unemployment"],
    "momentum+macro": ["momentum_3m", "d6_unemployment", "d6_tpm", "imacec_yoy"],
}
MIN_DIRECT_ROWS = 24


def macro_features(y: pd.Series, macro: pd.DataFrame) -> pd.DataFrame:
    """Features conocidas en cada mes ``t``. ``macro`` ya viene con el rezago de publicacion aplicado."""
    m = macro.reindex(y.index)
    feats = pd.DataFrame(index=y.index)
    feats["momentum_3m"] = y - y.shift(3)
    feats["d6_unemployment"] = m["unemployment_pct"] - m["unemployment_pct"].shift(6)
    feats["d6_tpm"] = m["tpm_pct"] - m["tpm_pct"].shift(6)
    feats["imacec_yoy"] = m["imacec_yoy_pct"]
    return feats


def _ols_predict(x_train: np.ndarray, y_train: np.ndarray, x_new: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(design, y_train, rcond=None)
    return float(beta[0] + x_new @ beta[1:])


def direct_rolling_origin(
    series: pd.Series, macro: pd.DataFrame, horizons=HORIZONS, min_train: int = MIN_TRAIN
) -> pd.DataFrame:
    """Pronostico directo a ``h`` meses: regresion OLS del cambio futuro sobre las features de hoy.

    En cada origen solo se entrena con pares (features en s, cambio entre s y s+h) cuyo desenlace ya
    se conocia en el origen, es decir ``s + h <= origen``. Misma grilla de origenes que
    ``rolling_origin`` para poder compararlos.
    """
    series = series.dropna().sort_index()
    feats = macro_features(series, macro)
    y = series.to_numpy()
    n = len(series)
    rows = []
    for origin in range(min_train, n):
        o = origin - 1  # posicion del ultimo dato conocido
        for h in horizons:
            target_pos = o + h
            if target_pos >= n:
                continue
            for name, cols in DIRECT_MODELS.items():
                x_all = feats[cols].to_numpy()
                idx = np.arange(0, o - h + 1)
                idx = idx[~np.isnan(x_all[idx]).any(axis=1)]
                if len(idx) < MIN_DIRECT_ROWS or np.isnan(x_all[o]).any():
                    continue
                delta = _ols_predict(x_all[idx], y[idx + h] - y[idx], x_all[o])
                pred = float(y[o] + delta)
                rows.append(
                    {
                        "origin": series.index[o], "target": series.index[target_pos], "h": h, "model": name,
                        "pred": pred, "actual": float(y[target_pos]), "abs_err": abs(pred - float(y[target_pos])),
                        "regime": regime_of(series.index[target_pos]),
                    }
                )
    return pd.DataFrame(rows)


def align_with_naive(direct: pd.DataFrame, baseline_errors: pd.DataFrame) -> pd.DataFrame:
    """Une los errores directos con los del ingenuo en los mismos (origen, horizonte)."""
    naive = baseline_errors[baseline_errors["model"] == "naive"]
    keys = direct[["origin", "h"]].drop_duplicates()
    # solo los (origen, h) donde TODOS los modelos directos existen: la comparacion debe ser sobre lo mismo
    full = direct.groupby(["origin", "h"])["model"].nunique()
    keys = full[full == len(DIRECT_MODELS)].reset_index()[["origin", "h"]]
    d = direct.merge(keys, on=["origin", "h"])
    n = naive.merge(keys, on=["origin", "h"])
    return pd.concat([d, n], ignore_index=True)
