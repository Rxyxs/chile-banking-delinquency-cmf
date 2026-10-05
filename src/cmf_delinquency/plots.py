"""Figuras del proyecto (matplotlib, fondo claro, paleta categórica validada)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from .analysis import REGIMES, dispersion, system_series  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BAND = "#efeeea"
SERIES = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a"}
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#e8f0fb", "#9cc0ef", "#2a78d6", "#123f78"])


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_system(panel: pd.DataFrame, path: Path) -> Path:
    s = system_series(panel)
    fig, ax = plt.subplots(figsize=(10, 4.8), facecolor=SURFACE)
    _style(ax)
    for name, start, end in REGIMES:
        x0 = pd.Timestamp(start)
        x1 = pd.Timestamp(end) if end else s.index.max()
        if name == "Alivio COVID":
            ax.axvspan(x0, x1, color=BAND, zorder=0)
        ax.text(x0 + (x1 - x0) / 2, 2.93, name, ha="center", va="center", fontsize=9, color=INK_2)
    ax.plot(s.index, s["total"], color=INK, linewidth=2.4, zorder=3, label="Total")
    for col, label, color in (
        ("comercial", "Comercial", SERIES["blue"]),
        ("consumo", "Consumo", SERIES["orange"]),
        ("vivienda", "Vivienda", SERIES["aqua"]),
    ):
        ax.plot(s.index, s[col], color=color, linewidth=1.6, zorder=2, label=label)
    ax.set_xlim(s.index.min(), s.index.max())
    ax.set_ylim(0.8, 3.05)
    ax.set_ylabel("Mora 90+ días (% de colocaciones)", color=INK_2, fontsize=9)
    ax.set_title(
        "Mora bancaria del sistema chileno, por cartera (CMF, 2016–2026)",
        loc="left", color=INK, fontsize=12, pad=12,
    )
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, ncol=4, loc="lower left", bbox_to_anchor=(0.0, -0.2))
    if s["imputed"].any():
        month = s.index[s["imputed"]][0]
        ax.annotate(
            f"{month:%Y-%m}: dato del sistema no publicado,\ninterpolado", xy=(month, s.loc[month, "total"]),
            xytext=(month - pd.Timedelta(days=330), 0.9), fontsize=8, color=INK_2,
            arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.8},
        )
    return _save(fig, path)


def fig_contributions(table: pd.DataFrame, path: Path, title: str) -> Path:
    t = table.sort_values("aporte_pp")
    fig, ax = plt.subplots(figsize=(8, 4.4), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.barh(t.index, t["aporte_pp"], color=SERIES["blue"], height=0.62)
    for y, v in enumerate(t["aporte_pp"]):
        ax.text(v + 0.006, y, f"{v:+.2f}", va="center", fontsize=9, color=INK)
    ax.set_xlabel("Aporte al alza de la mora del sistema (puntos porcentuales)", color=INK_2, fontsize=9)
    ax.set_title(title, loc="left", color=INK, fontsize=12)
    ax.set_xlim(0, t["aporte_pp"].max() * 1.15)
    return _save(fig, path)


def fig_dispersion(panel: pd.DataFrame, path: Path, portfolio: str = "consumo") -> Path:
    d = dispersion(panel, portfolio)
    fig, ax = plt.subplots(figsize=(10, 4.4), facecolor=SURFACE)
    _style(ax)
    ax.fill_between(d.index, d["p25"], d["p75"], color=SERIES["blue"], alpha=0.22, linewidth=0)
    ax.plot(d.index, d["mediana"], color=SERIES["blue"], linewidth=2)
    ax.text(d.index[-1] + pd.Timedelta(days=25), d["mediana"].iloc[-1], "Mediana", va="center", fontsize=9, color=INK)
    peak = d["iqr"].idxmax()
    ax.annotate(
        f"Mayor dispersión: {peak:%Y-%m}\n(rango intercuartil {d['iqr'].max():.2f} pp)",
        xy=(peak, d.loc[peak, "p75"]),
        xytext=(peak - pd.Timedelta(days=900), d["p75"].max() + 0.5),
        fontsize=9,
        color=INK_2,
        arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.8},
    )
    ax.set_xlim(d.index.min(), d.index.max() + pd.Timedelta(days=250))
    ax.set_ylabel(f"Mora 90+ días, cartera {portfolio} (%)", color=INK_2, fontsize=9)
    ax.set_title("Dispersión de la mora entre bancos (banda = percentiles 25–75)", loc="left", color=INK, fontsize=12)
    return _save(fig, path)


def fig_forecast(rows: pd.DataFrame, path: Path) -> Path:
    """rMAE por horizonte con IC 95%. ``rows``: columnas model, h, rmae, lo, hi."""
    models = [("arima_111", "ARIMA(1,1,1)", SERIES["blue"]), ("ets_damped", "ETS amortiguado", SERIES["orange"]), ("drift", "Deriva (24 m)", SERIES["aqua"])]
    horizons = sorted(rows["h"].unique())
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    width = 0.22
    for i, (key, label, color) in enumerate(models):
        sub = rows[rows["model"] == key].set_index("h").loc[horizons]
        x = np.arange(len(horizons)) + (i - 1) * width
        ax.errorbar(
            x, sub["rmae"], yerr=[sub["rmae"] - sub["lo"], sub["hi"] - sub["rmae"]],
            fmt="o", color=color, ecolor=color, markersize=7, markeredgecolor=SURFACE,
            markeredgewidth=1.5, elinewidth=1.6, capsize=0, label=label,
        )
    ax.axhline(1.0, color=INK, linewidth=1.2)
    ax.text(-0.45, 1.01, "Ingenuo = 1", ha="left", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(horizons)), [f"{h} mes" + ("es" if h > 1 else "") for h in horizons])
    ax.set_ylabel("MAE relativo al ingenuo (menor es mejor)", color=INK_2, fontsize=9)
    ax.set_title("¿Algún modelo le gana al pronóstico ingenuo? (IC 95%, bootstrap por bloques)", loc="left", color=INK, fontsize=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
    return _save(fig, path)


def fig_heatmap(panel: pd.DataFrame, path: Path) -> Path:
    p = panel[~panel["is_system"]].copy()
    p["year"] = p["date"].dt.year
    pivot = p.pivot_table(index="bank", columns="year", values="total", aggfunc="mean")
    pivot = pivot.dropna(thresh=4)
    # sucursales de bancos extranjeros sin cartera de personas: filas de puros ceros
    pivot = pivot[pivot.max(axis=1) >= 0.5]
    order = pivot.mean(axis=1).sort_values().index
    pivot = pivot.loc[order]
    fig, ax = plt.subplots(figsize=(10, 0.36 * len(pivot) + 1.6), facecolor=SURFACE)
    data = np.ma.masked_invalid(pivot.to_numpy())
    cmap = SEQ.copy()
    cmap.set_bad(GRID)
    im = ax.imshow(data, aspect="auto", cmap=cmap, vmin=0, vmax=np.nanpercentile(pivot.to_numpy(), 95))
    ax.set_xticks(range(pivot.shape[1]), pivot.columns, fontsize=9, color=INK_2)
    ax.set_yticks(range(pivot.shape[0]), pivot.index, fontsize=9, color=INK)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    threshold = np.nanpercentile(pivot.to_numpy(), 60)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.iat[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8, color="#ffffff" if v > threshold else INK)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(labelsize=8, colors=INK_2, length=0)
    ax.set_title("Mora 90+ días total por banco y año (promedio anual, %)", loc="left", color=INK, fontsize=12)
    return _save(fig, path)


MACRO_LABELS = {"unemployment_pct": "Desempleo", "tpm_pct": "Tasa de política monetaria", "imacec_yoy_pct": "IMACEC (var. anual)"}


def fig_leadlag(lead_lag: dict, path: Path) -> Path:
    """Correlación entre el cambio a 12 meses de la mora y el de cada indicador adelantado k meses."""
    colors = {"unemployment_pct": SERIES["blue"], "tpm_pct": SERIES["orange"], "imacec_yoy_pct": SERIES["aqua"]}
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    ax.axhline(0, color=INK_2, linewidth=0.9)
    for col, df in lead_lag.items():
        ax.plot(df["lag"], df["corr"], color=colors[col], linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.2, label=MACRO_LABELS[col])
    ax.set_xticks(range(0, 13))
    ax.set_xlabel("Meses que el indicador se adelanta a la mora", color=INK_2, fontsize=9)
    ax.set_ylabel("Correlación de cambios a 12 meses", color=INK_2, fontsize=9)
    ax.set_ylim(-0.8, 0.8)
    ax.set_title("¿Se mueven los indicadores antes que la mora?", loc="left", color=INK, fontsize=12, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, ncol=3, loc="lower left", bbox_to_anchor=(0.0, -0.28))
    return _save(fig, path)


def fig_macro_value(table: pd.DataFrame, path: Path) -> Path:
    """MAE de agregar macro, relativo al modelo con solo momentum (1 = no aporta; menor es mejor)."""
    models = [("momentum+unemployment", "Momentum + desempleo", SERIES["blue"]), ("momentum+macro", "Momentum + desempleo, TPM e IMACEC", SERIES["orange"])]
    horizons = sorted(table["h"].unique())
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    width = 0.22
    for i, (key, label, color) in enumerate(models):
        sub = table[table["model"] == key].set_index("h").loc[horizons]
        x = np.arange(len(horizons)) + (i - 0.5) * width
        ax.errorbar(x, sub["vs_momentum"], yerr=[sub["vs_momentum"] - sub["vs_momentum_lo"], sub["vs_momentum_hi"] - sub["vs_momentum"]],
                    fmt="o", color=color, ecolor=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5,
                    elinewidth=1.6, capsize=0, label=label)
    ax.axhline(1.0, color=INK, linewidth=1.2)
    ax.text(2.5, 1.02, "Solo momentum = 1", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(horizons)), [f"{h} mes" + ("es" if h > 1 else "") for h in horizons])
    ax.set_ylabel("MAE relativo al modelo sin macro (menor es mejor)", color=INK_2, fontsize=9)
    ax.set_title("¿Agregar indicadores macro mejora el pronóstico? (IC 95%)", loc="left", color=INK, fontsize=12, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left", bbox_to_anchor=(0.0, -0.1), ncol=2)
    return _save(fig, path)


BANK_MODEL_LABELS = {"ets_damped": "ETS amortiguado (por banco)", "pooled_gap": "Agrupado: momentum + brecha al sistema",
                     "pooled_system": "Agrupado: + momentum del sistema"}


def fig_bank_models(table: pd.DataFrame, path: Path) -> Path:
    """MAE promedio entre bancos relativo al ingenuo, con IC 95% por bootstrap sobre orígenes."""
    models = [("ets_damped", SERIES["blue"]), ("pooled_gap", SERIES["orange"]), ("pooled_system", SERIES["aqua"])]
    horizons = sorted(table["h"].unique())
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    width = 0.22
    for i, (key, color) in enumerate(models):
        sub = table[table["model"] == key].set_index("h").loc[horizons]
        x = np.arange(len(horizons)) + (i - 1) * width
        ax.errorbar(x, sub["vs_naive"], yerr=[sub["vs_naive"] - sub["vs_naive_lo"], sub["vs_naive_hi"] - sub["vs_naive"]],
                    fmt="o", color=color, ecolor=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5,
                    elinewidth=1.6, capsize=0, label=BANK_MODEL_LABELS[key])
    ax.axhline(1.0, color=INK, linewidth=1.2)
    ax.text(1.5, 1.004, "Ingenuo = 1", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(horizons)), [f"{h} mes" + ("es" if h > 1 else "") for h in horizons])
    ax.set_ylabel("MAE relativo al ingenuo (menor es mejor)", color=INK_2, fontsize=9)
    ax.set_title("Pronóstico de la mora por banco: ¿algún modelo le gana al ingenuo?", loc="left", color=INK, fontsize=12, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left", bbox_to_anchor=(0.0, -0.1), ncol=2)
    return _save(fig, path)


def fig_bank_detail(detail: pd.DataFrame, h: int, path: Path) -> Path:
    """MAE relativo al ingenuo, banco por banco, a un horizonte."""
    order = detail[detail["model"] == "pooled_system"].sort_values("rmae")["bank"].tolist()
    models = [("pooled_system", SERIES["aqua"]), ("ets_damped", SERIES["blue"])]
    fig, ax = plt.subplots(figsize=(8.5, 0.5 * len(order) + 1.8), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    for i, (key, color) in enumerate(models):
        sub = detail[detail["model"] == key].set_index("bank").loc[order]
        y = np.arange(len(order)) + (i - 0.5) * 0.28
        ax.errorbar(sub["rmae"], y, xerr=[sub["rmae"] - sub["lo"], sub["hi"] - sub["rmae"]], fmt="o", color=color, ecolor=color,
                    markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5, elinewidth=1.6, capsize=0,
                    label=BANK_MODEL_LABELS[key])
    ax.axvline(1.0, color=INK, linewidth=1.2)
    ax.set_yticks(range(len(order)), order, fontsize=9, color=INK)
    ax.set_xlabel(f"MAE relativo al ingenuo a {h} meses (menor es mejor)", color=INK_2, fontsize=9)
    ax.set_title(f"Banco por banco a {h} meses (IC 95%)", loc="left", color=INK, fontsize=12, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left", bbox_to_anchor=(0.0, -0.12), ncol=2)
    return _save(fig, path)
