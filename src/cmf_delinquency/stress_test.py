"""Prueba de tension macro de la mora bancaria: modelo satelite estimado con datos reales + Monte Carlo.

El modelo satelite liga el cambio a 12 meses de la mora 90+ del sistema (por cartera) con el cambio a
12 meses de la TPM y del desempleo y con el IMACEC anual, todos adelantados ``LAG`` meses:

    d12 mora_t = a + b_tpm * d12 TPM_{t-6} + b_des * d12 desempleo_{t-6} + b_ima * IMACEC_{t-6} + e_t

Decisiones y por que:

* **Se excluye el periodo de alivio COVID (2020-03 a 2021-12) de la estimacion.** En esos meses el
  desempleo subio y la mora bajo (reprogramaciones, retiros de AFP, ayudas fiscales): con la muestra
  completa el desempleo sale con signo negativo, que es un artefacto de politica y no la respuesta
  normal del credito. Un escenario adverso sin esas ayudas no deberia heredar ese signo.
* **Errores HAC (Newey-West, 12 rezagos).** Los cambios a 12 meses se solapan y los residuos estan
  autocorrelacionados; los errores de MCO subestimarian la incertidumbre de los coeficientes.
* **Monte Carlo con dos fuentes de incertidumbre:** coeficientes (normal multivariada con la
  covarianza HAC) y residuos (remuestreo de los residuos historicos). Los shocks macro son los del
  escenario: es un ejercicio condicional, no un pronostico.
* **La mora 90+ se usa como proxy de PD.** Es un stock (saldo con mas de 90 dias de atraso sobre
  colocaciones), no una tasa de default a 12 meses; la perdida que se reporta es la perdida sobre
  ese stock: ``mora * LGD * EAD``.
* **EAD = colocaciones implicitas del ultimo mes** (mora en MM$ / mora en %), un dato real. **La LGD
  es un supuesto**: Beta con media 45% (la LGD supervisora de Basilea para deuda senior no
  garantizada) y desviacion 10 pp; se puede cambiar.

Uso:
    python -m cmf_delinquency.stress_test
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .analysis import implied_loans, system_series

ROOT = Path(__file__).resolve().parents[2]
PANEL_CSV = ROOT / "data" / "panel_mora90.csv"
MACRO_CSV = ROOT / "data" / "macro_indicators.csv"

LAG = 6
WINDOW = 12
HAC_LAGS = 12
FACTORS = ("d_tpm_pp", "d_unemployment_pp", "imacec_yoy_pct")
PORTFOLIOS = ("total", "comercial", "consumo", "vivienda")
COVID_RELIEF = ("2020-03-01", "2021-12-01")
LGD_MEAN = 0.45
LGD_SD = 0.10
MORA_BOUNDS = (0.0, 100.0)


@dataclass(frozen=True)
class StressScenario:
    """Shocks macro de un escenario, expresados como en el modelo.

    ``tpm_shock_bp``: cambio de la TPM en 12 meses, en puntos base.
    ``unemployment_delta_pp``: cambio del desempleo en 12 meses, en puntos porcentuales.
    ``imacec_growth``: IMACEC, variacion anual (%), al final de esos 12 meses.
    """

    name: str
    tpm_shock_bp: float
    unemployment_delta_pp: float
    imacec_growth: float

    def factors(self) -> np.ndarray:
        return np.array([self.tpm_shock_bp / 100.0, self.unemployment_delta_pp, self.imacec_growth])


@dataclass(frozen=True)
class SatelliteFit:
    """Resultado de estimar el modelo satelite para una cartera."""

    portfolio: str
    params: pd.Series
    cov: pd.DataFrame
    tvalues: pd.Series
    residuals: np.ndarray
    r2: float
    n_obs: int
    sample: tuple[str, str]
    factor_range: dict[str, tuple[float, float]]

    def predict(self, x: np.ndarray) -> float:
        return float(self.params.iloc[0] + self.params.iloc[1:].to_numpy() @ x)


def design(mora: pd.Series, macro: pd.DataFrame, lag: int = LAG, exclude_covid: bool = True) -> pd.DataFrame:
    """Tabla de estimacion: ``y`` = cambio a 12 meses de la mora; factores macro adelantados ``lag`` meses."""
    out = pd.DataFrame(
        {
            "y": mora.diff(WINDOW),
            "d_tpm_pp": macro["tpm_pct"].diff(WINDOW).shift(lag),
            "d_unemployment_pp": macro["unemployment_pct"].diff(WINDOW).shift(lag),
            "imacec_yoy_pct": macro["imacec_yoy_pct"].shift(lag),
        }
    ).dropna()
    if exclude_covid:
        start, end = (pd.Timestamp(d) for d in COVID_RELIEF)
        out = out[(out.index < start) | (out.index > end)]
    return out


def fit_satellite(mora: pd.Series, macro: pd.DataFrame, portfolio: str = "total", lag: int = LAG,
                  exclude_covid: bool = True) -> SatelliteFit:
    data = design(mora, macro, lag, exclude_covid)
    if len(data) < 24:
        raise ValueError(f"Muy pocas observaciones para estimar ({len(data)}); se necesitan al menos 24")
    X = sm.add_constant(data[list(FACTORS)])
    res = sm.OLS(data["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return SatelliteFit(
        portfolio=portfolio,
        params=res.params,
        cov=res.cov_params(),
        tvalues=res.tvalues,
        residuals=res.resid.to_numpy(),
        r2=float(res.rsquared),
        n_obs=int(res.nobs),
        sample=(f"{data.index.min():%Y-%m}", f"{data.index.max():%Y-%m}"),
        factor_range={f: (float(data[f].min()), float(data[f].max())) for f in FACTORS},
    )


def beta_params(mean: float, sd: float) -> tuple[float, float]:
    """Parametros (a, b) de una Beta con la media y desviacion pedidas."""
    if not 0 < mean < 1:
        raise ValueError("La media de la LGD debe estar entre 0 y 1")
    var = sd**2
    if var <= 0 or var >= mean * (1 - mean):
        raise ValueError("Desviacion de la LGD fuera de rango para esa media")
    k = mean * (1 - mean) / var - 1
    return mean * k, (1 - mean) * k


@dataclass
class CreditRiskStressEngine:
    """Motor de estres calibrado con el panel CMF y las series macro."""

    fits: dict[str, SatelliteFit]
    current_mora: dict[str, float]
    ead_mm: float
    as_of: str
    lgd_mean: float = LGD_MEAN
    lgd_sd: float = LGD_SD
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_data(cls, panel: pd.DataFrame, macro: pd.DataFrame, portfolios: tuple[str, ...] = PORTFOLIOS,
                  lag: int = LAG, exclude_covid: bool = True) -> CreditRiskStressEngine:
        sys_ = system_series(panel)
        last = sys_.index.max()
        fits = {p: fit_satellite(sys_[p], macro, p, lag, exclude_covid) for p in portfolios}
        row = sys_.loc[last]
        ead = float(implied_loans(pd.DataFrame({"total": [row["total"]], "mora90_mm": [row["mora90_mm"]]})).iloc[0])
        return cls(
            fits=fits,
            current_mora={p: float(row[p]) for p in portfolios},
            ead_mm=ead,
            as_of=f"{last:%Y-%m}",
        )

    @classmethod
    def from_csv(cls, panel_csv: Path = PANEL_CSV, macro_csv: Path = MACRO_CSV, **kwargs) -> CreditRiskStressEngine:
        panel = pd.read_csv(panel_csv, parse_dates=["date"])
        macro = pd.read_csv(macro_csv, parse_dates=["month"]).set_index("month")
        return cls.from_data(panel, macro, **kwargs)

    def out_of_range(self, scenario: StressScenario, portfolio: str = "total") -> list[str]:
        """Factores del escenario que caen fuera de lo observado en la muestra (extrapolacion)."""
        fit = self.fits[portfolio]
        return [f for f, v in zip(FACTORS, scenario.factors()) if not fit.factor_range[f][0] <= v <= fit.factor_range[f][1]]

    def simulate(self, scenario: StressScenario, portfolio: str = "total", n_sims: int = 10_000,
                 seed: int | None = 42, lgd_mean: float | None = None, lgd_sd: float | None = None) -> dict:
        """Distribucion de la mora estresada (pp) y, para la cartera total, de la perdida (MM$)."""
        if portfolio not in self.fits:
            raise KeyError(f"Cartera desconocida: {portfolio}. Opciones: {sorted(self.fits)}")
        if n_sims < 100:
            raise ValueError("n_sims debe ser al menos 100")
        rng = np.random.default_rng(seed)
        fit = self.fits[portfolio]
        x = np.concatenate([[1.0], scenario.factors()])

        coefs = rng.multivariate_normal(fit.params.to_numpy(), fit.cov.to_numpy(), size=n_sims)
        noise = rng.choice(fit.residuals, size=n_sims, replace=True)
        delta = coefs @ x + noise
        current = self.current_mora[portfolio]
        stressed = np.clip(current + delta, *MORA_BOUNDS)

        out = {
            "scenario_name": scenario.name,
            "portfolio": portfolio,
            "as_of": self.as_of,
            "n_sims": n_sims,
            "current_mora_pct": current,
            "point_delta_pp": fit.predict(scenario.factors()),
            "mean_mora_pct": float(stressed.mean()),
            "p05_mora_pct": float(np.percentile(stressed, 5)),
            "p95_mora_pct": float(np.percentile(stressed, 95)),
            "p99_mora_pct": float(np.percentile(stressed, 99)),
            "prob_increase": float((stressed > current).mean()),
            "out_of_sample_range": self.out_of_range(scenario, portfolio),
        }
        if portfolio == "total":
            a, b = beta_params(lgd_mean if lgd_mean is not None else self.lgd_mean,
                               lgd_sd if lgd_sd is not None else self.lgd_sd)
            lgd = rng.beta(a, b, size=n_sims)
            loss = stressed / 100.0 * lgd * self.ead_mm
            # Misma LGD simulada para hoy y para el escenario: la incertidumbre de la LGD escala el
            # incremento, no se suma como ruido sobre todo el stock actual.
            extra = (stressed - current) / 100.0 * lgd * self.ead_mm
            base_loss = current / 100.0 * (a / (a + b)) * self.ead_mm
            out.update(
                {
                    "ead_mm": self.ead_mm,
                    "current_loss_mm": base_loss,
                    "mean_loss_mm": float(loss.mean()),
                    "p95_loss_mm": float(np.percentile(loss, 95)),
                    "p99_loss_mm": float(np.percentile(loss, 99)),
                    "mean_extra_loss_mm": float(extra.mean()),
                    "var99_extra_loss_mm": float(np.percentile(extra, 99)),
                    "unexpected_loss_99_mm": float(np.percentile(loss, 99) - loss.mean()),
                }
            )
        return out

    def summary(self) -> pd.DataFrame:
        rows = []
        for p, f in self.fits.items():
            row = {"cartera": p, "n": f.n_obs, "r2": f.r2, "desde": f.sample[0], "hasta": f.sample[1]}
            for k in FACTORS:
                row[k] = float(f.params[k])
                row[f"t_{k}"] = float(f.tvalues[k])
            rows.append(row)
        return pd.DataFrame(rows).set_index("cartera")


def historical_scenario(macro: pd.DataFrame, month: str, name: str) -> StressScenario:
    """Escenario con los cambios macro efectivamente observados en los 12 meses que terminan en ``month``."""
    m = pd.Timestamp(month)
    d = macro.diff(WINDOW).loc[m]
    return StressScenario(name=name, tpm_shock_bp=round(float(d["tpm_pct"]) * 100, 2),
                          unemployment_delta_pp=round(float(d["unemployment_pct"]), 4),
                          imacec_growth=round(float(macro.loc[m, "imacec_yoy_pct"]), 4))


def default_scenarios(macro: pd.DataFrame) -> list[StressScenario]:
    """Base, dos escenarios historicos (de la muestra) y uno hipotetico severo."""
    return [
        StressScenario("Base: sin cambios", 0.0, 0.0, 2.0),
        historical_scenario(macro, "2022-12-01", "Histórico: ciclo de alzas 2022"),
        historical_scenario(macro, "2016-12-01", "Histórico: desaceleración 2016"),
        StressScenario("Hipotético: alza de tasas con recesión", 300.0, 2.0, -3.0),
    ]


def stress_grid(macro: pd.DataFrame, panel: pd.DataFrame | None = None, n_sims: int = 10_000,
                engine: CreditRiskStressEngine | None = None, seed: int = 42) -> pd.DataFrame:
    """Corre todos los escenarios por defecto sobre todas las carteras."""
    engine = engine or CreditRiskStressEngine.from_data(panel, macro)
    rows = []
    for sc in default_scenarios(macro):
        for p in engine.fits:
            r = engine.simulate(sc, p, n_sims=n_sims, seed=seed)
            r["tpm_shock_bp"], r["unemployment_delta_pp"], r["imacec_growth"] = sc.tpm_shock_bp, sc.unemployment_delta_pp, sc.imacec_growth
            r["out_of_sample_range"] = ",".join(r["out_of_sample_range"])
            rows.append(r)
    out = pd.DataFrame(rows)
    base = out[out["scenario_name"] == out["scenario_name"].iloc[0]].set_index("portfolio")
    out["mean_vs_base_pp"] = out["mean_mora_pct"] - out["portfolio"].map(base["mean_mora_pct"])
    out["extra_loss_vs_base_mm"] = out["mean_extra_loss_mm"] - out["portfolio"].map(base["mean_extra_loss_mm"])
    return out


def conditional_backtest(mora: pd.Series, macro: pd.DataFrame, start: str = "2023-01-01", lag: int = LAG) -> pd.DataFrame:
    """Validacion fuera de muestra del modelo condicional.

    Para cada mes ``t`` desde ``start`` se estima con datos hasta ``t-12`` (asi ningun cambio a 12
    meses usado en la estimacion se solapa con el que se predice) y se predice el cambio a 12 meses
    de la mora con la macro efectivamente observada. Se compara con "la mora no cambia" (delta 0).
    Es lo que hace una prueba de tension: si los shocks hubieran sido conocidos, cuanto se acierta.
    """
    full = design(mora, macro, lag, exclude_covid=False)
    rows = []
    for t in full.index[full.index >= pd.Timestamp(start)]:
        cutoff = t - pd.DateOffset(months=WINDOW)
        fit = fit_satellite(mora.loc[:cutoff], macro.loc[:cutoff], lag=lag)
        x = full.loc[t, list(FACTORS)].to_numpy(dtype=float)
        rows.append({"date": t, "actual": float(full.at[t, "y"]), "pred": fit.predict(x)})
    out = pd.DataFrame(rows).set_index("date")
    out["err_model"] = out["actual"] - out["pred"]
    out["err_naive"] = out["actual"]
    return out


def main() -> None:
    engine = CreditRiskStressEngine.from_csv()
    macro = pd.read_csv(MACRO_CSV, parse_dates=["month"]).set_index("month")
    print(f"Calibrado con datos hasta {engine.as_of}; EAD (colocaciones implicitas) = ${engine.ead_mm:,.0f} MM")
    print(engine.summary()[["n", "r2", *FACTORS]].round(3).to_string())
    for sc in default_scenarios(macro):
        r = engine.simulate(sc)
        print(f"\n=== {r['scenario_name']} ===  (TPM {sc.tpm_shock_bp:+.0f} pb, "
              f"desempleo {sc.unemployment_delta_pp:+.1f} pp, IMACEC {sc.imacec_growth:+.1f}%)")
        print(f"Mora total: {r['current_mora_pct']:.2f}% -> {r['mean_mora_pct']:.2f}% "
              f"(P95 {r['p95_mora_pct']:.2f}%, P99 {r['p99_mora_pct']:.2f}%)")
        print(f"Perdida adicional media: ${r['mean_extra_loss_mm']:,.0f} MM | VaR 99% adicional: ${r['var99_extra_loss_mm']:,.0f} MM")
        if r["out_of_sample_range"]:
            print(f"Aviso: fuera del rango historico en {r['out_of_sample_range']}")


if __name__ == "__main__":
    main()
