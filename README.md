# Chilean bank delinquency, 2016–2026 — a monthly panel from the CMF

[English ] | [[Español](README.es.md) ]

![tests](https://github.com/Rxyxs/chile-banking-delinquency-cmf/actions/workflows/ci.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![System delinquency by portfolio](reports/figures/01_mora_sistema.png)

**[Interactive page](https://rxyxs.github.io/chile-banking-delinquency-cmf/)**: explore any bank against the system and read the forecasting results.

## Why this project

Bank delinquency is the first number anyone asks for when they want to know whether Chilean credit is getting worse, and the CMF publishes it every month. But it is published as **128 separate Excel files**, one per month, in **three different layouts**. I wanted to turn that into one clean panel and answer seven questions an analyst actually gets asked:

1. How big was the COVID-era drop in arrears, and how much of it has come back?
2. Is the recent rise a *system-wide* deterioration, or is it a few banks, or a shift in who lends?
3. Can a simple model forecast next quarter's delinquency better than "same as today"?
4. Do macro indicators (unemployment, the policy rate, IMACEC) improve those forecasts?
5. Can an individual bank's delinquency be forecast, by borrowing strength across banks?
6. Under a macro stress scenario, how far would arrears rise, and can that model be trusted?
7. Does a machine-learning model do better, and what does it rely on?

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

**Macro indicators (finding 5).** Monthly unemployment, policy rate (TPM) and IMACEC from [mindicador.cl](https://mindicador.cl), an open API that mirrors Banco Central and INE series. It is a third-party aggregator, not the official publisher, so figures can differ from the official ones or be revised later; I use the values as they stood when I downloaded them (2026-10-03), not real-time vintages. The small table is committed at [`data/macro_indicators.csv`](data/macro_indicators.csv). CPI is left out because the API only returns it up to 2025-12.

**Loan mix by bank (findings 7 and 8).** Commercial, consumer (with credit cards) and mortgage loans of each bank, in MM$, from the CMF [*Reporte Financiero Mensual*](https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28910.html), sheet "Activos Bancos 2", December 2019 to December 2025. The parser reads both the pre-2022 layout and the new accounting compendium by locating headers. The table is committed at [`data/loan_mix.csv`](data/loan_mix.csv).

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

### 5. Macro indicators do not improve the forecast

I tested three monthly indicators: unemployment, the policy rate and IMACEC (annual change). Unemployment and IMACEC are lagged one month for publication, so a forecast only uses what was known at its origin.

**They do move before arrears, with signs that need care.** Correlation between the 12-month change in arrears and the 12-month change in each indicator, with the indicator leading by *k* months (116 overlapping observations):

| Indicator | Same month | Leading by 6 months | Leading by 12 months |
|---|---|---|---|
| Policy rate (TPM) | −0.14 | +0.39 | **+0.67** |
| Unemployment | +0.16 | −0.27 | **−0.51** |
| IMACEC (annual change) | −0.40 | −0.34 | −0.11 |

![Lead-lag correlations](reports/figures/06_macro_rezagos.png)

- The policy rate, a year earlier, correlates strongly with the rise in arrears: consistent with rate rises passing through to borrowers, which I did not test as a causal claim.
- Unemployment has the *wrong* sign at long leads. Unemployment rose sharply in 2020 while arrears fell, because of the relief measures, and that episode dominates a sample this short.
- These are changes over overlapping 12-month windows, so neighbouring correlations are not independent and I give no p-values. It is a description, not a test.

**But adding them makes the forecasts worse.** Direct forecasts at each horizon (least squares of the future change on today's features), with the same expanding-origin protocol as finding 4 (68 origins at one month). The reference is the same model without macro, so the table isolates what the indicators add. Below 1 means better.

| Horizon | Momentum only, vs naive | + unemployment, vs momentum only | + unemployment, TPM and IMACEC, vs momentum only |
|---|---|---|---|
| 1 month | 0.95 [0.87, 1.06] | 1.11 [1.01, 1.21] | 1.14 [1.03, 1.27] |
| 3 months | **0.82 [0.70, 0.97]** | 1.24 [1.04, 1.47] | 1.30 [0.99, 1.70] |
| 6 months | 0.98 [0.80, 1.13] | 1.22 [0.97, 1.47] | 1.21 [0.73, 1.95] |
| 12 months | 1.13 [1.02, 1.28] | 1.12 [0.89, 1.24] | 1.10 [0.61, 1.91] |

![Value of adding macro indicators](reports/figures/07_macro_aporte.png)

- Adding macro raises the error by 10 to 30% relative to momentum alone. At 1 and 3 months for unemployment, and at 1 month for all three, the interval excludes 1: it is worse, not just no better. Elsewhere the intervals include 1.
- Momentum alone (the change over the last three months) beats the naive forecast only at 3 months (0.82, about the same as the ARIMA of finding 4) and is *worse* than naive at 12 months.
- **I did not test why macro hurts.** A plausible cause is that in the training windows the COVID relief reversed the usual link between unemployment and arrears, so the coefficients learned there mislead afterwards; the unemployment row of the correlation table is the symptom. With 60 to 120 months, three extra regressors can also simply overfit.

### 6. Individual banks are close to a random walk

Forecasting one bank's arrears is harder than forecasting the system: each series is short and noisy. A natural idea is to borrow strength across banks with a single pooled regression whose features include the bank's **gap to the system** (does a bank far above the system drift back toward it?) and the system's own momentum. I tested it on the 10 banks with at least 100 months of data and a median share of at least 1% of system loans. The rest are foreign branches and small banks whose arrears jump from 0% to 4% on a single loan and would dominate any average error.

Same protocol as finding 4 (68 origins at one month). The table gives the mean absolute error across banks relative to the naive forecast, with a block bootstrap that resamples by month (banks in the same month share the month's shock, so resampling banks one by one would understate the uncertainty). Below 1 is better.

| Horizon | Naive error (pp) | ETS per bank | Pooled: momentum + gap | Pooled: also system momentum |
|---|---|---|---|---|
| 1 month | 0.09 | 1.01 [0.99, 1.03] | 1.01 [0.99, 1.02] | 0.99 [0.97, 1.00] |
| 3 months | 0.16 | 0.99 [0.97, 1.01] | 1.00 [0.98, 1.03] | **0.96 [0.92, 1.00]** |
| 6 months | 0.24 | 0.98 [0.94, 1.03] | 1.00 [0.97, 1.05] | 0.98 [0.91, 1.04] |
| 12 months | 0.33 | 0.99 [0.94, 1.06] | 1.06 [1.03, 1.15] | 1.08 [1.03, 1.17] |

![Per-bank forecast models against the naive forecast](reports/figures/08_bancos_modelos.png)

- **No model clearly beats "same as today" at any horizon.** The closest is the pooled model with the system's momentum at 3 months (0.96), whose interval touches 1.00.
- **The gap to the system adds nothing.** Comparing the pooled model with the gap against the same model without it gives 1.00 at every horizon up to 6 months (intervals within 0.98 to 1.02): no evidence of mean reversion toward the system level in this sample. I checked that the method can see it when it exists: on synthetic banks built with a 15% monthly reversion it cuts the error by 13% (0.87 [0.81, 0.94]), and with no reversion it does not (1.04 [1.01, 1.08]).
- **At 12 months the pooled models are worse** than naive (1.06 and 1.08, intervals above 1).
- **ETS is almost identical to naive** because a damped trend on these smooth series stays nearly flat.

![Bank by bank at 6 months](reports/figures/09_bancos_detalle.png)

Bank by bank at 6 months, two intervals for the pooled model exclude 1: Banco Consorcio (0.87 [0.81, 0.92]) and Scotiabank Chile (0.88 [0.77, 0.98]). With 20 intervals (10 banks, 2 models), one or two falling outside by chance is expected, so I do not read them as banks that are predictable.

Limits: total arrears only, 10 banks, no correction for multiple comparisons, and the errors are small in absolute terms (0.09 to 0.33 pp), so an edge of 2 to 4% is a few hundredths of a percentage point.

### 7. Stress test: interest rates drive consumer arrears; the data cannot say what a recession would do

Finding 5 asked whether macro data help *forecast*. A stress test asks a different, conditional question: *if* rates, unemployment and activity moved like this, where would arrears go? I estimate one satellite regression per portfolio on the system series, then simulate it.

```
12-month change in arrears_t = a + b1·Δ12 TPM_{t-L} + b2·Δ12 unemployment_{t-L} + b3·IMACEC y/y_{t-L} + e_t
```

Four modelling decisions, each forced by something in the data:

- **The COVID relief window (2020-03 to 2021-12) is excluded from estimation.** With it, unemployment gets the *wrong* sign (−0.15 pp of consumer arrears per pp of unemployment, t = −12.3): arrears fell while unemployment rose under deferrals, pension withdrawals and transfers. A stress scenario without those programmes should not inherit that.
- **The lag L is chosen per portfolio** from 0, 3, 6, 9 and 12 months by adjusted R² on a common sample. My first version fixed L = 6 after looking at the data. Fixing the lag in hindsight makes the model look better than it is: for consumer arrears a fixed 6-month lag scores 0.53 against the honest 0.73 (see below). Now the lag is re-chosen at every backtest origin using only the past.
- **Sign restrictions.** Unemployment and IMACEC move together (correlation −0.77), and even outside COVID their separate coefficients come out with economically wrong signs. Unrestricted, the model says a recession *lowers* consumer arrears. When a factor has the wrong sign it is dropped (coefficient 0) and the model re-estimated, and the engine reports which factors it dropped.
- **Newey-West errors (12 lags)**, because the 12-month changes overlap. The Monte Carlo draws coefficients from that covariance and resamples historical residuals (10,000 draws, fixed seed). EAD is the real implied loan book in 2026-08 (CLP 250 trillion). LGD is an assumed Beta with mean 45% (the Basel supervisory value for senior unsecured debt).

| Portfolio | Lag | R² | Δ12 TPM (per pp) | IMACEC y/y (per %) | Dropped for wrong sign |
|---|---|---|---|---|---|
| Total | 9 | 0.57 | +0.039 (t 4.2) | −0.022 (t −4.6) | unemployment |
| Commercial | 12 | 0.67 | +0.059 (t 10.3) | −0.009 (t −1.8) | unemployment |
| **Consumer** | 9 | **0.80** | **+0.095 (t 9.4)** | — | unemployment, IMACEC |
| Mortgage | 3 | 0.18 | — | −0.021 (t −1.3) | TPM (unemployment kept: +0.075, t 1.4) |

**Does it work out of sample?** For each month from 2023-01 to 2026-08 I re-estimate with data up to 12 months earlier (lag and sign restrictions included), feed in the macro that actually happened, and compare with "arrears do not change". The bars show the honest score, with the lag chosen from the past. The grey dots show what each fixed lag would have scored. Picking the best dot after the fact is the leak I had.

![Out-of-sample check of the stress model](reports/figures/11_estres_validacion.png)

- **Consumer: 0.73** (0.26 pp against 0.36 pp, 44 months). It beats no change, though by less than the fixed-lag version suggested.
- **Commercial: 0.85.** It also beats no change, once the wrong-signed unemployment term is gone.
- **Total: 1.12, mortgage: 1.53.** Neither beats no change, so I read those scenarios as illustrations.
- **The lag matters as much as the model.** Total and commercial would score 0.74 and 0.57 at a fixed 12-month lag, and consumer 0.53 at 6 months. None of those can be chosen honestly in advance.

**Is the rate effect stable?** Fitting consumer arrears on pre-COVID data alone (2017–2020, when the TPM barely moved: −1 to +0.5 pp) gives +0.14 pp per pp (t = 3.0), against +0.08 (t = 9.4) since 2022. The sign and size hold, but the precision comes almost entirely from the 2022–23 cycle.

**Which banks are most exposed?** The same model, bank by bank, on the 10 banks with enough history and size:

![Consumer arrears sensitivity to the policy rate by bank](reports/figures/12_estres_bancos_tpm.png)

BancoEstado (+0.15 pp per 100 bp), BCI (+0.12), Scotiabank (+0.10) and Itaú (+0.09) react three to ten times more than Bice (+0.02), Consorcio (+0.01) and Security (+0.03). The hypothesis that all banks share one coefficient is rejected by a wide margin (Cochran's Q = 94 on 9 df), although Q overstates the evidence because the banks share the same cycle. **Does the loan mix explain it?** The arrears files only give percentages, so I took each bank's loan book by portfolio from a second CMF source, the *Reporte Financiero Mensual* (sheet "Activos Bancos 2", December 2019–2025, both accounting layouts). The association is positive but weak, and none of it is significant with 10 banks:

| Bank trait (2019–2025 average) | Spearman with rate sensitivity | Permutation p |
|---|---|---|
| Consumer loans / total loans | 0.55 | 0.11 |
| Credit cards / consumer loans | 0.52 | 0.13 |
| Current consumer arrears | 0.48 | 0.16 |

BancoEstado (7.5% consumer) and BCI (8.0%) are the most sensitive banks with *less* consumer lending than Santander (14.5%) or Banco de Chile (13.9%), so the loan mix is not the explanation. A client-income channel is plausible but untested: the CMF does not publish borrower income by bank.

**Can the stress test be taken down to each bank?** Not with these data. Out of sample (2023–2026, same protocol), relative to "no change", pooled over the 10 banks:

| How each bank's 12-month change is projected | Relative MAE |
|---|---|
| Satellite model estimated on the bank itself | 1.63 |
| Two stages: macro → system (validated model) → bank via its own beta to the system | 1.22 |
| Same second stage, given the *actual* system change (not a forecast) | 0.98 |

Even knowing the system's path perfectly, a bank's beta to the system barely beats no change: most of a bank's movement is its own, not the common cycle. The exception is the large consumer lenders, which do follow the system (BCI 0.53, Scotiabank 0.65, Itaú 0.68, BancoEstado 0.75 with the actual system change). Niche banks (Consorcio 1.95, Internacional 2.29) do not. So the engine and the API report system-level stress only, and I do not publish loss figures by bank.

**Scenarios**, all as 12-month shocks. The two historical ones replay the changes actually observed in the 12 months to that date:

| Scenario | TPM | Unemployment | IMACEC | Consumer arrears | Total arrears | Total vs base | Extra loss vs base |
|---|---|---|---|---|---|---|---|
| Base: no change | 0 bp | 0 pp | +2.0% | 2.35% → 2.45% | 2.44% → 2.59% | — | — |
| Historical: 2022 hiking cycle | +725 bp | +0.7 pp | −1.0% | → **3.14%** [2.85, 3.47] | → 2.94% | +0.35 pp | CLP 390 bn |
| Historical: 2016 slowdown | 0 bp | +0.3 pp | +1.2% | → 2.45% | → 2.61% | +0.02 pp | CLP 20 bn |
| Hypothetical: hikes with recession | +300 bp | +2.0 pp | −3.0% | → 2.74% | → 2.82% | +0.23 pp | CLP 256 bn |

Brackets are the 5th–95th percentiles. The base case rises about 0.15 pp because the intercept carries the sample's average upward drift, which is why effects are reported against the base.

- **The hypothetical recession adds almost nothing beyond its rate hike.** For consumer credit the unemployment and activity terms were dropped, so the +2 pp unemployment shock has no effect. The data contain no recession outside COVID: the estimation sample never saw IMACEC below −2.5% or unemployment rising more than 1.2 pp in a year. That is a limit of the data, not a finding that recessions are harmless, and the engine flags out-of-range shocks (`out_of_sample_range`) and dropped factors (`factors_dropped`).
- **Arrears × LGD × EAD is a loss on the delinquent stock, not a 12-month expected loss.** 90+ arrears are a stock ratio, not a default rate. The CLP figures show orders of magnitude only and are not a provisioning estimate.

![Stress scenarios by portfolio](reports/figures/10_estres_escenarios.png)

### 8. Machine learning does not beat "no change" either; SHAP shows why

Findings 4 to 6 used linear and exponential-smoothing models. Could a non-linear model do better at the bank level? `models/ml_shap.py` trains a LightGBM regressor on the 10 eligible banks to forecast each bank's change in arrears 3 and 6 months ahead. It uses the bank's own dynamics (level, 3/6/12-month changes, gap to the system), the system's momentum, and the macro known in that month (publication lags applied). At every origin from 2021 it is retrained only on outcomes already known, and compared with "no change" and with a pooled linear regression on the same features. MAE relative to no change, 95% block-bootstrap interval:

| Portfolio | Horizon | Pooled linear | LightGBM |
|---|---|---|---|
| Consumer | 3 months | 1.66 [1.30, 2.02] | 1.52 [1.34, 1.71] |
| Consumer | 6 months | 2.31 [1.37, 3.04] | 1.61 [1.38, 1.96] |
| Total | 3 months | 1.09 [1.02, 1.19] | 1.02 [0.97, 1.08] |
| Total | 6 months | 1.30 [1.01, 1.55] | 1.03 [0.93, 1.13] |

- **Neither model beats no change.** For consumer arrears both are clearly worse. LightGBM is less bad than the linear model because the trees cannot extrapolate. For total arrears LightGBM ties with no change.
- **Dropping the COVID window from training does not rescue it** (consumer at 6 months: 1.85). The early origins lose most of their training data.

**SHAP** (TreeExplainer) decomposes each forecast exactly: base value + one contribution per feature = forecast (the additivity error is below 1e-9, and a test checks it).

![Global SHAP summary](reports/figures/shap_summary.png)

The audit finding is the ranking itself: the most important feature is the **level** of the policy rate, ahead of its change. In a sample with one tightening cycle, the rate level works as a clock that tells the model which regime it is in, not as a cause, and that is consistent with the model failing out of sample. The local explanation for BancoEstado in 2026-08 shows the same thing: of a forecast of −0.19 pp at 6 months, −0.15 pp comes from the rate and −0.15 pp from the bank's own dynamics.

![Local SHAP explanation for BancoEstado](reports/figures/13_shap_local.png)

SHAP explains what the model does, not what drives arrears. Here its main use is to show why a model that fits well in sample should not be deployed. The full output (global importance, one decomposition per bank, the backtest and the model parameters) is in `reports/shap_explanations.json`.

### Serving it: DuckDB warehouse and a REST API

The same data and engine are packaged for use outside the notebook:

- **`warehouse.py`** builds `warehouse/delinquency.duckdb` from the committed CSVs with layered SQL models in `src/cmf_delinquency/sql/` (staging → `dim_banco` → `fct_mora_banco_mes` → `mart_sistema_macro`). Each build replaces the tables and then runs data-quality checks (no duplicate bank-months, one system row per month, loan shares summing to 1). A test checks that the SQL version of the model's factors matches the Python one to 1e-9.
- **`api.py`** is a FastAPI service that calibrates the engine once at start-up. Endpoints: `GET /health`, `GET /model` (coefficients), `GET /scenarios` and `POST /simulate/stress-test`. Inputs are validated (bounded shocks, valid portfolio, a feasible LGD), so a bad request returns 422 and not 500.
- **Docker:** `docker compose up --build` serves the API on port 8000 with a health check, running as a non-root user. `docker compose --profile batch run --rm warehouse` builds the warehouse in a container.

```bash
curl -X POST localhost:8000/simulate/stress-test -H "content-type: application/json" \
     -d '{"portfolio": "consumo", "tpm_shock_bp": 300, "unemployment_delta_pp": 1, "imacec_growth": -1}'
```

## Limitations

- **Arrears are not losses.** 90+ day delinquency says nothing about recoveries, provisions or write-offs.
- **The attribution in finding 2 is accounting, not causality.** It says *where* the rise happened. It does not say why. The relief measures of 2020–21 are context I did not test.
- **Loan balances are implied, not published.** The CMF gives arrears in % and in MM$, not the loan stock, so I back it out as `MM$ / (% / 100)`. It is only defined where arrears are positive, so banks at 0% drop out of the weights. This is why the reconstructed system figure in the decomposition (2.49%) sits slightly above the official one (2.44%).
- **Small backtest.** 56–68 overlapping origins on one regime-shifting series. The intervals are wide and the evaluation window starts in 2021, so it mostly measures the post-COVID rebound.
- **Entity histories are not fully comparable.** Names change in the source (Itaú Corpbanca → Banco Itaú Chile, BBVA Chile → Scotiabank Azul), the BBVA/Scotiabank Azul series ends in 2018-08 and Banco Security is no longer reported after 2025-10. I handle the renames I could identify in the files; I did not research the corporate transactions behind them.
- **Macro data are not real-time vintages.** They come from a third-party aggregator and are the values available on the download date; later revisions would not be visible. The one-month publication lag I apply to unemployment and IMACEC is an assumption I did not check against the official calendars, and I only tried linear models.
- **The stress model rests on 94 overlapping monthly observations** and one tightening-and-easing cycle, with no recession outside COVID. The lag and sign choices are themselves data-driven. The per-bank sensitivities come from the same short sample and use total consumer arrears, not loan-level data.
- **The loan-mix test has 10 banks.** Spearman correlations on 10 points have very wide intervals, so "not significant" means "not shown", not "no effect". The loan mix uses December snapshots, not every month.
- **The per-bank study covers 10 banks** chosen by data length and size, not all 24 entities, and it compares many intervals without correcting for it. A bank that looks predictable at one horizon is most likely noise.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=src                                # Windows PowerShell: $env:PYTHONPATH="src"

python -m cmf_delinquency.pipeline --offline         # uses the committed panel, ~30 s
python -m cmf_delinquency.pipeline                   # downloads the 128 files and the macro series first
python -m cmf_delinquency.stress_test               # stress scenarios in the terminal
python -m cmf_delinquency.warehouse                  # DuckDB warehouse in warehouse/
uvicorn cmf_delinquency.api:app --port 8000          # REST API (or: docker compose up --build)
pytest                                               # 170 tests, no network
```

Outputs: `reports/results.json`, `reports/tables/*.csv`, `reports/figures/*.png`.

## Layout

```
src/cmf_delinquency/
  download.py   scrape the index page, fetch the monthly .xlsx (idempotent)
  parse.py      three layouts -> one tidy panel, name aliases, mergers
  analysis.py   regimes, within/mix decomposition, dispersion, rank persistence
  macro.py      open macro indicators (mindicador.cl) and publication lags
  banks.py      per-bank forecasts: pooled models across banks, bank selection
  forecast.py   rolling-origin backtest, block-bootstrap intervals
  stress_test.py  satellite model (lag selection, sign restrictions, HAC), Monte Carlo scenarios, nested out-of-sample check, per-bank sensitivity
  warehouse.py  DuckDB warehouse built from the SQL models in sql/, with data-quality checks
  api.py        FastAPI service for the stress engine
  models/ml_shap.py  LightGBM per-bank forecasts, rolling-origin backtest, SHAP explanations
  plots.py      figures
  site.py       builds the GitHub Pages page (docs/index.html) from the panel and results.json
  pipeline.py   end to end
docs/           the GitHub Pages site (generated; do not edit by hand)
tests/          170 tests: synthetic files in both layouts + integrity checks on the real panel + macro, per-bank, page, no-look-ahead, stress, warehouse and API checks
Dockerfile, docker-compose.yml   container for the API (and a batch job for the warehouse)
```

## License

MIT. The underlying data belongs to the Comisión para el Mercado Financiero (CMF).
