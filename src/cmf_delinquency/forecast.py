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
    errors: pd.DataFrame, model: str, h: int, n_boot: int = 4000, seed: int = 0
) -> tuple[float, float, float]:
    """rMAE de model vs ingenuo con IC 95% por bootstrap de bloques.

    Los errores de orígenes consecutivos se solapan (comparten el mismo tramo de
    historia), así que se remuestrean bloques de largo max(h, 3) y no puntos sueltos.
    """
    sub = errors[errors["h"] == h].sort_values("origin")
    e_m = sub[sub["model"] == model]["abs_err"].to_numpy()
    e_n = sub[sub["model"] == "naive"]["abs_err"].to_numpy()
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
