"""Pronostico de la mora por banco con LightGBM y explicacion con SHAP.

Objetivo: el cambio de la mora de cada banco a ``h`` meses (3 y 6), \\(y_{t+h} - y_t\\). El pronostico
ingenuo ("no cambia") predice 0, asi que es el benchmark natural.

Atributos, todos conocidos en ``t``:

* dinamica propia: nivel, cambios a 3, 6 y 12 meses, brecha respecto del sistema;
* sistema: cambio a 3 meses de la mora del sistema;
* macro, con su rezago de publicacion (desempleo e IMACEC se conocen un mes despues): nivel de la
  TPM, cambio a 12 meses de la TPM y del desempleo, IMACEC anual.

Evaluacion por origen movil: en cada origen se reentrena solo con pares (t, t+h) cuyo desenlace ya
se conocia, se predice y se compara con el ingenuo y con una regresion lineal agrupada sobre los
mismos atributos. Los intervalos son por bootstrap de bloques sobre el error medio entre bancos de
cada origen (los bancos de un mismo mes comparten el shock).

SHAP (TreeExplainer) da una descomposicion aditiva exacta de cada prediccion: valor base + aporte
de cada atributo = prediccion. Es una herramienta de auditoria del modelo (que atributos usa y con
que signo), no una prueba causal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .. import forecast as F
from .. import macro as M
from ..banks import eligible_banks, per_origin, wide_series

HORIZONS = (3, 6)
SEED = 42
FIRST_ORIGIN = "2021-01-01"
MIN_TRAIN_ROWS = 200
OWN = ("nivel", "mom3", "mom6", "mom12", "brecha_sistema")
SYSTEM = ("sistema_mom3",)
MACRO = ("tpm", "d12_tpm", "d12_desempleo", "imacec_anual")
FEATURES = (*OWN, *SYSTEM, *MACRO)
# Grupos para la explicacion local: suma de los aportes SHAP de sus atributos.
GROUPS = {
    "TPM": ("tpm", "d12_tpm"),
    "Desempleo": ("d12_desempleo",),
    "IMACEC": ("imacec_anual",),
    "Dinámica propia del banco": OWN,
    "Sistema": SYSTEM,
}
LGBM_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 7,
    "min_child_samples": 20,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "random_state": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "n_jobs": 1,
    "verbose": -1,
}


def build_panel(panel: pd.DataFrame, macro: pd.DataFrame, system: pd.Series, portfolio: str = "consumo",
                banks: list[str] | None = None) -> pd.DataFrame:
    """Tabla larga banco x mes con los atributos en ``t`` y los objetivos ``y_h`` (cambio a h meses)."""
    banks = banks or eligible_banks(panel, portfolio)
    wide = wide_series(panel, banks, portfolio)
    sys_ = system.reindex(wide.index)
    known = M.apply_publication_lag(macro).reindex(wide.index)
    macro_feats = pd.DataFrame(
        {
            "tpm": known["tpm_pct"],
            "d12_tpm": known["tpm_pct"].diff(12),
            "d12_desempleo": known["unemployment_pct"].diff(12),
            "imacec_anual": known["imacec_yoy_pct"],
        }
    )
    frames = []
    for bank in banks:
        y = wide[bank]
        df = pd.DataFrame(
            {
                "nivel": y,
                "mom3": y - y.shift(3),
                "mom6": y - y.shift(6),
                "mom12": y - y.shift(12),
                "brecha_sistema": y - sys_,
                "sistema_mom3": sys_ - sys_.shift(3),
            },
            index=wide.index,
        ).join(macro_feats)
        for h in HORIZONS:
            df[f"y_{h}"] = y.shift(-h) - y
        df.insert(0, "bank", bank)
        frames.append(df)
    out = pd.concat(frames).rename_axis("date").reset_index()
    return out.dropna(subset=list(FEATURES)).reset_index(drop=True)


def _lgbm():
    from lightgbm import LGBMRegressor

    return LGBMRegressor(**LGBM_PARAMS)


def _ols(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    x = np.column_stack([np.ones(len(train)), train[list(FEATURES)].to_numpy()])
    beta, *_ = np.linalg.lstsq(x, train[target].to_numpy(), rcond=None)
    return np.column_stack([np.ones(len(test)), test[list(FEATURES)].to_numpy()]) @ beta


def rolling_origin(data: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS, first_origin: str = FIRST_ORIGIN) -> pd.DataFrame:
    """Errores por banco, origen, horizonte y modelo (naive, ols_agrupado, lightgbm)."""
    rows = []
    origins = sorted(data.loc[data["date"] >= pd.Timestamp(first_origin), "date"].unique())
    for h in horizons:
        target = f"y_{h}"
        for origin in origins:
            origin = pd.Timestamp(origin)
            known_until = origin - pd.DateOffset(months=h)  # desenlace t+h <= origen
            train = data[(data["date"] <= known_until)].dropna(subset=[target])
            test = data[(data["date"] == origin)].dropna(subset=[target])
            if len(train) < MIN_TRAIN_ROWS or test.empty:
                continue
            model = _lgbm().fit(train[list(FEATURES)], train[target])
            preds = {
                "naive": np.zeros(len(test)),
                "ols_agrupado": _ols(train, test, target),
                "lightgbm": model.predict(test[list(FEATURES)]),
            }
            for name, pred in preds.items():
                for bank, actual, p in zip(test["bank"], test[target], pred):
                    rows.append({"origin": origin, "h": h, "model": name, "bank": bank, "abs_err": abs(actual - p)})
    return pd.DataFrame(rows)


def backtest_table(errors: pd.DataFrame) -> pd.DataFrame:
    pooled = per_origin(errors)
    rows = []
    for h in sorted(pooled["h"].unique()):
        n = int(pooled[(pooled["h"] == h) & (pooled["model"] == "naive")].shape[0])
        mae_naive = float(pooled[(pooled["h"] == h) & (pooled["model"] == "naive")]["abs_err"].mean())
        for model in ("ols_agrupado", "lightgbm"):
            point, lo, hi = F.rmae_ci(pooled, model, int(h), seed=SEED)
            rows.append({"h": int(h), "model": model, "origenes": n, "mae_naive_pp": mae_naive, "rmae": point, "lo": lo, "hi": hi})
    return pd.DataFrame(rows)


@dataclass
class ShapReport:
    horizon: int
    base_value: float
    global_importance: pd.Series
    local: list[dict]
    values: np.ndarray
    features: pd.DataFrame


def explain(data: pd.DataFrame, h: int = 6) -> tuple[object, ShapReport]:
    """Entrena con todos los pares de desenlace conocido y explica con SHAP el ultimo mes del panel.

    Solo entran los bancos con dato en ese mes: un banco que dejo de reportar no se explica con
    atributos viejos.
    """
    import shap

    target = f"y_{h}"
    train = data.dropna(subset=[target])
    model = _lgbm().fit(train[list(FEATURES)], train[target])
    explainer = shap.TreeExplainer(model)
    x_train = train[list(FEATURES)]
    values = explainer.shap_values(x_train)
    base = float(np.ravel(explainer.expected_value)[0])

    latest = data[data["date"] == data["date"].max()]
    x_latest = latest[list(FEATURES)]
    local_values = explainer.shap_values(x_latest)
    preds = model.predict(x_latest)
    local = []
    for (_, row), contrib, pred in zip(latest.iterrows(), local_values, preds):
        per_feature = dict(zip(FEATURES, map(float, contrib)))
        local.append(
            {
                "bank": row["bank"],
                "date": f"{row['date']:%Y-%m}",
                "mora_actual": float(row["nivel"]),
                "base_value": base,
                "prediction_pp": float(pred),
                "aportes_grupo": {g: float(sum(per_feature[f] for f in fs)) for g, fs in GROUPS.items()},
                "aportes_atributo": per_feature,
                "atributos": {f: float(row[f]) for f in FEATURES},
                "error_aditividad": float(abs(base + contrib.sum() - pred)),
            }
        )
    importance = pd.Series(np.abs(values).mean(axis=0), index=FEATURES).sort_values(ascending=False)
    return model, ShapReport(h, base, importance, local, values, x_train)


def shap_summary_plot(report: ShapReport, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap

    plt.figure(figsize=(9, 5.5))
    # summary_plot dispersa los puntos con el generador global de numpy: se fija solo mientras dibuja
    # para que la figura sea identica entre corridas, y despues se restaura el estado anterior.
    state = np.random.get_state()
    np.random.seed(SEED)
    try:
        shap.summary_plot(report.values, report.features, show=False, plot_size=None, color_bar=True)
    finally:
        np.random.set_state(state)
    ax = plt.gca()
    ax.set_title(f"SHAP: qué mueve el pronóstico de la mora de consumo a {report.horizon} meses", loc="left", fontsize=12)
    ax.set_xlabel("Aporte SHAP a la predicción del cambio de mora (pp)")
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=160, bbox_inches="tight", facecolor="#fcfcfb")
    plt.close("all")
    return path


def shap_local_plot(report: ShapReport, bank: str, path: Path) -> Path:
    """Descomposicion aditiva de la prediccion de un banco: valor base + aporte de cada grupo = prediccion."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    item = next(x for x in report.local if x["bank"] == bank)
    groups = item["aportes_grupo"]
    labels = ["Valor base", *groups, "Predicción"]
    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    running = item["base_value"]
    edges = [0.0, running, item["prediction_pp"]]
    ax.barh(0, running, color="#9a9893")
    for i, (name, value) in enumerate(groups.items(), start=1):
        ax.barh(i, value, left=running, color="#eb6834" if value > 0 else "#2a78d6")
        ax.text(running + value + (0.004 if value >= 0 else -0.004), i, f"{value:+.3f}", va="center",
                ha="left" if value >= 0 else "right", fontsize=9, color="#0b0b0b")
        running += value
        edges.append(running)
    ax.barh(len(labels) - 1, item["prediction_pp"], color="#0b0b0b")
    ax.text(item["prediction_pp"], len(labels) - 1, f"  {item['prediction_pp']:+.3f} pp", va="center",
            ha="left" if item["prediction_pp"] >= 0 else "right", fontsize=9)
    span = max(edges) - min(edges)
    ax.set_xlim(min(edges) - 0.25 * span, max(edges) + 0.25 * span)
    ax.axvline(0, color="#0b0b0b", linewidth=0.8)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_xlabel(f"Cambio de la mora de consumo a {report.horizon} meses (pp)", fontsize=9)
    ax.set_title(f"SHAP local: {bank}, {item['date']} (mora actual {item['mora_actual']:.2f}%)", loc="left", fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="#fcfcfb")
    plt.close(fig)
    return path


def export_json(report: ShapReport, backtest: pd.DataFrame, path: Path) -> Path:
    payload = {
        "horizonte_meses": report.horizon,
        "valor_base_pp": report.base_value,
        "importancia_global_mean_abs_shap": report.global_importance.to_dict(),
        "explicaciones_locales": report.local,
        "backtest": backtest.to_dict(orient="records"),
        "parametros_lightgbm": LGBM_PARAMS,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
