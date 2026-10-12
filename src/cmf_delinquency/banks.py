"""Pronostico de la mora por banco, con modelos que toman informacion entre bancos.

Cada banco tiene pocas observaciones y es ruidoso, asi que un modelo por banco tiene poco que
aprender. La alternativa es un modelo agrupado: una sola regresion sobre todos los bancos, cuyas
features incluyen la brecha del banco respecto del sistema (si un banco esta muy por sobre el
sistema, tiende a volver?) y el momentum del sistema.

El protocolo es el mismo que para el sistema: origen movil, solo se entrena con pares cuyo
desenlace ya se conocia en el origen, y se compara contra el pronostico ingenuo.
"""
from __future__ import annotations

import time
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


# ------------------------------------------------------------------------------------------------
# Composicion de la cartera por banco (Reporte Financiero Mensual de la CMF)
#
# El archivo de mora entrega solo porcentajes y el monto moroso total, no el saldo de cada cartera.
# El Reporte Financiero Mensual (hoja "Activos Bancos 2") si trae las colocaciones comerciales,
# de consumo (con el detalle de tarjetas de credito) y de vivienda de cada banco, en MM$.
# Hay dos formatos: el antiguo (hasta 2021) y el del nuevo Compendio de Normas Contables (desde
# 2022). Las columnas se ubican por su encabezado, no por posicion, para leer ambos.
RFM_INDEX_URL = "https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28910.html"
RFM_SHEET = "Activos Bancos 2"
LOAN_MIX_MONTHS = tuple(f"{y}-12" for y in range(2019, 2026))


def _find_col(header: pd.DataFrame, *prefixes: str) -> int:
    for col in header.columns:
        for cell in header[col].dropna().astype(str):
            if any(cell.strip().lower().startswith(p.lower()) for p in prefixes):
                return int(col)
    raise ValueError(f"No se encontro una columna que empiece con {prefixes}")


def parse_loan_mix(path, month: str) -> pd.DataFrame:
    """Colocaciones por banco (MM$) y participacion de consumo y de tarjetas, de un Reporte Financiero Mensual."""
    raw = pd.read_excel(path, sheet_name=RFM_SHEET, header=None)
    header = raw.iloc[:12]
    name_col = _find_col(header, "Instituciones")
    cols = {
        "comercial_mm": _find_col(header, "Colocaciones comerci", "Comerciales (1)"),
        "consumo_mm": _find_col(header, "Consumo (1)"),
        "tarjetas_mm": _find_col(header, "Tarjetas de cr", "Deudores por Tarjetas"),
        "vivienda_mm": _find_col(header, "Vivienda (1)"),
    }
    body = raw.iloc[12:]
    body = body[body[name_col].astype(str).str.strip().ne("") & body[name_col].notna()]
    out = pd.DataFrame({"bank_raw": body[name_col].astype(str).str.strip()})
    for key, col in cols.items():
        out[key] = pd.to_numeric(body[col], errors="coerce")
    out = out.dropna(subset=["consumo_mm", "comercial_mm"])
    out = out[~out["bank_raw"].str.lower().str.startswith(("sistema", "nota", "fuente", "("))]
    out["loans_mm"] = out[["comercial_mm", "consumo_mm", "vivienda_mm"]].sum(axis=1)
    out = out[out["loans_mm"] > 0]
    out["consumo_share"] = out["consumo_mm"] / out["loans_mm"]
    out["tarjetas_share_consumo"] = (out["tarjetas_mm"] / out["consumo_mm"]).where(out["consumo_mm"] > 0)
    out.insert(0, "month", month)
    return out.reset_index(drop=True)


def rfm_candidates(html: str) -> dict[str, list[str]]:
    """Archivos de cada mes en el orden de la pagina. La pagina mezcla el reporte con anexos y cuadros
    del mismo mes; el reporte suele ser el primero, pero se valida abriendo el archivo."""
    from .download import _LINK_RE, MESES

    out: dict[str, list[str]] = {}
    for filename, label in _LINK_RE.findall(html):
        mes, _, anio = label.strip().lower().partition(" ")
        if mes in MESES and anio.strip().isdigit():
            out.setdefault(f"{int(anio)}-{MESES[mes]:02d}", []).append(filename)
    return out


def _has_sheet(path, sheet: str = RFM_SHEET) -> bool:
    try:
        return sheet in pd.ExcelFile(path).sheet_names
    except Exception:
        return False


def download_loan_mix(raw_dir, months: tuple[str, ...] = LOAN_MIX_MONTHS, delay: float = 0.4) -> pd.DataFrame:
    """Baja los Reportes Financieros Mensuales pedidos y devuelve la composicion de cartera de cada banco."""
    from pathlib import Path

    import requests

    from .download import BASE_URL, USER_AGENT
    from .parse import canonical_bank

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    index: dict[str, list[str]] | None = None
    frames = []
    for month in months:
        target = raw_dir / f"{month}.xlsx"
        if not _has_sheet(target):
            if index is None:
                resp = session.get(RFM_INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
                resp.raise_for_status()
                index = rfm_candidates(resp.text)
            for filename in index.get(month, []):
                r = session.get(BASE_URL + filename, headers={"User-Agent": USER_AGENT}, timeout=60)
                r.raise_for_status()
                target.write_bytes(r.content)
                time.sleep(delay)
                if _has_sheet(target):
                    break
            else:
                raise RuntimeError(f"No se encontro el Reporte Financiero Mensual de {month}")
        mix = parse_loan_mix(target, month)
        mix["bank"] = [canonical_bank(b, pd.Timestamp(f"{month}-01")) for b in mix["bank_raw"]]
        frames.append(mix.dropna(subset=["bank"]))
    return pd.concat(frames, ignore_index=True)


def loan_mix_profile(mix: pd.DataFrame) -> pd.DataFrame:
    """Promedio por banco de la participacion de consumo y de tarjetas en los meses disponibles."""
    return mix.groupby("bank").agg(
        consumo_share=("consumo_share", "mean"),
        tarjetas_share_consumo=("tarjetas_share_consumo", "mean"),
        loans_mm=("loans_mm", "mean"),
        n_meses=("month", "nunique"),
    )


def explain_sensitivity(sensitivity: pd.DataFrame, profile: pd.DataFrame,
                        features: tuple[str, ...] = ("consumo_share", "tarjetas_share_consumo", "mora_actual")) -> pd.DataFrame:
    """Correlacion de rangos (Spearman) entre la sensibilidad a la TPM de cada banco y rasgos de su cartera.

    Con ~10 bancos esto describe asociaciones, no causas: un rho de 0,6 tiene un IC muy ancho y el
    p-valor por permutacion se reporta para no leer ruido como explicacion.
    """
    df = sensitivity.join(profile, how="inner")
    rows = []
    rng = np.random.default_rng(42)
    for feat in features:
        pair = df[["beta_tpm", feat]].dropna()
        rho = float(pair["beta_tpm"].rank().corr(pair[feat].rank()))
        perms = np.array([pair["beta_tpm"].rank().corr(pd.Series(rng.permutation(pair[feat].rank().to_numpy()),
                                                                index=pair.index)) for _ in range(5000)])
        rows.append({"rasgo": feat, "n_bancos": int(len(pair)), "spearman": rho,
                     "p_permutacion": float((np.abs(perms) >= abs(rho) - 1e-12).mean())})
    return pd.DataFrame(rows).set_index("rasgo")
