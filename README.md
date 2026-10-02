# Chilean bank delinquency, 2016–2026 — a monthly panel from the CMF

[Versión en español](README.es.md) · English

![tests](https://github.com/Rxyxs/chile-banking-delinquency-cmf/actions/workflows/ci.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![System delinquency by portfolio](reports/figures/01_mora_sistema.png)

## Why this project

Bank delinquency is the first number anyone asks for when they want to know whether Chilean credit is getting worse, and the CMF publishes it every month. But it is published as **128 separate Excel files**, one per month, in **three different layouts**. I wanted to turn that into one clean panel and answer three questions an analyst actually gets asked:

1. How big was the COVID-era drop in arrears, and how much of it has come back?
2. Is the recent rise a *system-wide* deterioration, or is it a few banks, or a shift in who lends?
3. Can a simple model forecast next quarter's delinquency better than "same as today"?

Everything runs from one command and every number below comes from that run.

## Data

Source: [CMF Chile — *Indicador de morosidad de 90 días o más individual del Sistema Bancario*](https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28914.html). Public, no API key.

| | |
|---|---|
| Months | 128 (2016-01 → 2026-08) |
| Rows | 2,453 (bank × month) |
| Entities | 24 banks + the official "Sistema Bancario" row |
| Measure | % of loans 90+ days past due, for total, commercial, personas, consumo and vivienda; plus the arrears amount in MM$ |

The small tidy panel is committed at [`data/panel_mora90.csv`](data/panel_mora90.csv) so tests and `--offline` runs need no network. Raw `.xlsx` files are downloaded on demand and not versioned.

### Things the files do that a naive reader would get wrong

- **Three layouts.** 2016-01–2021-12 (9 columns, bank name in column A), 2022-01–2023-03 (12 columns, no text headers on the % block), 2023-04 onwards (12 columns with headers). The parser detects the layout and **refuses to guess**: if the expected headers are not where they should be it raises.
- **No break at the 2022 change.** The system total goes 1.259% → 1.273% from 2021-12 to 2022-01, so the layout change is not a definition change (there is a test for it).
- **`---` is not zero.** It means the bank has no such portfolio. It is kept as `NaN`.
- **Mergers and renames.** `Itaú Corpbanca` became `Banco Itaú Chile`; `BBVA Chile` became `Scotiabank Azul`; `Jp Morgan…`/`JP Morgan…` differ only by case. The *old* `Banco Itaú Chile` of 2016-01…03 is a different, pre-merger entity and is excluded from the continuous series.
- **A real hole in the source.** In the 2023-07 file the CMF left the "Sistema Bancario" row as `---` although all 18 banks are present. That single month is interpolated linearly and flagged (`imputed`); a gap longer than one month raises instead of being invented.

## Findings

### 1. The COVID relief was large and has fully reversed

| Regime | System total (mean) | Comercial | Consumo | Vivienda |
|---|---|---|---|---|
| Pre-COVID (2016-01 → 2020-02) | 1.94% | 1.67% | 1.99% | 2.48% |
| COVID relief (2020-03 → 2021-12) | 1.65% | 1.73% | 1.46% | 1.60% |
| Normalisation (2022-01 →) | 2.14% | 2.30% | 2.18% | 1.94% |

System delinquency was **2.04% in Feb 2020**, fell to a minimum of **1.26% in Dec 2021** (−0.78 pp) and is **2.44% in Aug 2026**: a rebound of **+1.18 pp**, ending **0.40 pp above where it started**. The portfolios did not move together. Household credit swung far more than commercial credit:

| Portfolio | Feb 2020 | Minimum | Aug 2026 | Fall to minimum | Rebound since |
|---|---|---|---|---|---|
| Commercial | 1.90% | 1.42% (2021-12) | 2.34% | −0.47 pp | +0.92 pp |
| Consumo | 2.17% | 0.98% (2021-10) | 2.35% | −1.18 pp | +1.36 pp |
| Vivienda | 2.30% | 1.04% (2022-03) | 2.65% | −1.26 pp | +1.61 pp |

Mortgage arrears are now the furthest above their pre-COVID level among the household portfolios (+0.35 pp, against +0.18 pp for consumo), and commercial arrears show the largest gap against Feb 2020 of the three (+0.45 pp), even though they swung the least.

### 2. The rise since the trough is deterioration inside banks, not a change in who lends

Decomposing the +1.25 pp change between Dec 2021 and Aug 2026 into *within-bank* change and *mix* change (Kitagawa, on the 11 banks present at both dates, covering 96–99.7% of loans):

| Component | pp |
|---|---|
| Within-bank deterioration | **+1.27** |
| Mix (shifts in bank market share) | −0.02 |
| Total | +1.25 |

Three banks explain about two thirds of it: **Santander-Chile (+0.36 pp), Banco del Estado (+0.33 pp) and Scotiabank Chile (+0.17 pp)**.

![Contribution by bank](reports/figures/02_aporte_bancos.png)

### 3. Banks converge in a crisis and diverge in a recovery

The spread between banks in consumer arrears (interquartile range) peaked at **2.14 pp in July 2024** and is **0.42 pp** now. The *ranking* of banks is moderately persistent: the Spearman rank correlation of consumer arrears between Dec 2019 and Aug 2026 is **0.69**.

![Dispersion across banks](reports/figures/03_dispersion_consumo.png)

![Heatmap by bank and year](reports/figures/05_mapa_calor_bancos.png)

### 4. Beating "same as today" is hard, and the evidence is thin

Rolling-origin backtest of the system total (first forecast after 60 months of history, 68 origins at the 1-month horizon). Metric: MAE relative to the naive forecast (1.0 = same as naive), with a 95% block-bootstrap interval.

| Horizon | ARIMA(1,1,1) | ETS damped | 24-month drift |
|---|---|---|---|
| 1 month | 0.94 [0.87, 1.02] | 0.98 [0.88, 1.08] | 1.04 [0.90, 1.22] |
| 3 months | **0.83 [0.73, 0.95]** | 0.85 [0.71, 1.00] | 1.05 [0.79, 1.37] |
| 6 months | 0.88 [0.75, 1.03] | 0.87 [0.70, 1.06] | 1.12 [0.72, 1.64] |
| 12 months | 0.94 [0.83, 1.14] | 0.91 [0.77, 1.15] | 1.39 [0.89, 2.63] |

**Only ARIMA at 3 months has an interval that excludes 1.** Everywhere else I cannot show an edge over the naive forecast, and extrapolating the recent trend (drift) is *worse* at long horizons. A seasonal-naive forecast is far worse (rMAE 8.4 at 1 month): arrears have no stable seasonality.

![Backtest](reports/figures/04_backtest_rmae.png)

## Limitations

- **Arrears are not losses.** 90+ day delinquency says nothing about recoveries, provisions or write-offs.
- **The attribution in finding 2 is accounting, not causality.** It says *where* the rise happened. It does not say why. The relief measures of 2020–21 are context I did not test.
- **Loan balances are implied, not published.** The CMF gives arrears in % and in MM$, not the loan stock, so I back it out as `MM$ / (% / 100)`. It is only defined where arrears are positive, so banks at 0% drop out of the weights. This is why the reconstructed system figure in the decomposition (2.49%) sits slightly above the official one (2.44%).
- **Small backtest.** 56–68 overlapping origins on one regime-shifting series. The intervals are wide and the evaluation window starts in 2021, so it mostly measures the post-COVID rebound.
- **Entity histories are not fully comparable.** Names change in the source (Itaú Corpbanca → Banco Itaú Chile, BBVA Chile → Scotiabank Azul), the BBVA/Scotiabank Azul series ends in 2018-08 and Banco Security is no longer reported after 2025-10. I handle the renames I could identify in the files; I did not research the corporate transactions behind them.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=src                                # Windows PowerShell: $env:PYTHONPATH="src"

python -m cmf_delinquency.pipeline --offline         # uses the committed panel, ~30 s
python -m cmf_delinquency.pipeline                   # downloads the 128 files first
pytest                                               # 49 tests, no network
```

Outputs: `reports/results.json`, `reports/tables/*.csv`, `reports/figures/*.png`.

## Layout

```
src/cmf_delinquency/
  download.py   scrape the index page, fetch the monthly .xlsx (idempotent)
  parse.py      three layouts -> one tidy panel, name aliases, mergers
  analysis.py   regimes, within/mix decomposition, dispersion, rank persistence
  forecast.py   rolling-origin backtest, block-bootstrap intervals
  plots.py      figures
  pipeline.py   end to end
tests/          49 tests: synthetic files in both layouts + integrity checks on the real panel
```

## License

MIT. The underlying data belongs to the Comisión para el Mercado Financiero (CMF).
