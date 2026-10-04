# Morosidad bancaria en Chile, 2016–2026 — un panel mensual con datos de la CMF

Español · [English version](README.md)

![tests](https://github.com/Rxyxs/chile-banking-delinquency-cmf/actions/workflows/ci.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![Morosidad del sistema por cartera](reports/figures/01_mora_sistema.png)

## Por qué este proyecto

La morosidad bancaria es lo primero que se pregunta cuando se quiere saber si el crédito en Chile se está deteriorando, y la CMF la publica todos los meses. Pero la publica en **128 archivos Excel separados**, uno por mes, con **tres formatos distintos**. Quise convertir eso en un solo panel limpio y responder cuatro preguntas que un analista recibe de verdad:

1. ¿Qué tan grande fue la caída de la mora durante el COVID y cuánto ha vuelto?
2. ¿El alza reciente es un deterioro de *todo el sistema*, de unos pocos bancos, o un cambio en quién presta?
3. ¿Un modelo simple pronostica la mora del próximo trimestre mejor que "igual que hoy"?
4. ¿Mejoran esos pronósticos los indicadores macro (desempleo, tasa de política monetaria, IMACEC)?

Todo corre con un solo comando y cada número de abajo sale de esa corrida.

## Datos

Fuente: [CMF Chile — *Indicador de morosidad de 90 días o más individual del Sistema Bancario*](https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28914.html). Público, sin clave de API.

| | |
|---|---|
| Meses | 128 (2016-01 → 2026-08) |
| Filas | 2.453 (banco × mes) |
| Entidades | 24 bancos + la fila oficial "Sistema Bancario" |
| Medida | % de colocaciones con 90+ días de atraso, para total, comercial, personas, consumo y vivienda; más el monto moroso en MM$ |

El panel limpio, que es pequeño, está versionado en [`data/panel_mora90.csv`](data/panel_mora90.csv): los tests y las corridas con `--offline` no necesitan red. Los `.xlsx` originales se descargan al ejecutar y no se versionan.

**Indicadores macro (hallazgo 5).** Desempleo, tasa de política monetaria (TPM) e IMACEC mensuales desde [mindicador.cl](https://mindicador.cl), una API abierta que replica series del Banco Central y del INE. Es un agregador de terceros, no el publicador oficial, así que las cifras pueden diferir de las oficiales o revisarse después; uso los valores tal como estaban al descargarlos (2026-10-03), no versiones en tiempo real. La tabla, pequeña, está versionada en [`data/macro_indicators.csv`](data/macro_indicators.csv). El IPC queda fuera porque la API solo lo entrega hasta 2025-12.

### Cosas que hacen los archivos y que un lector ingenuo interpretaría mal

- **Tres formatos.** 2016-01–2021-12 (9 columnas, nombre del banco en la columna A), 2022-01–2023-03 (12 columnas, sin encabezados de texto en el bloque de %) y 2023-04 en adelante (12 columnas con encabezados). El parser detecta el formato y **no adivina**: si los encabezados esperados no están donde corresponde, falla con un error.
- **Sin quiebre en el cambio de 2022.** El total del sistema pasa de 1,259% a 1,273% entre 2021-12 y 2022-01, así que el cambio de formato no es un cambio de definición (hay un test para eso).
- **`---` no es cero.** Significa que el banco no tiene esa cartera. Se conserva como `NaN`.
- **Fusiones y cambios de nombre.** `Itaú Corpbanca` pasó a llamarse `Banco Itaú Chile`; `BBVA Chile` pasó a `Scotiabank Azul`; `Jp Morgan…` y `JP Morgan…` difieren solo en mayúsculas. El `Banco Itaú Chile` *antiguo* de 2016-01 a 2016-03 es otra entidad, previa a la fusión, y se excluye de la serie continua.
- **Un hueco real en la fuente.** En el archivo de 2023-07 la CMF dejó la fila "Sistema Bancario" en `---` aunque los 18 bancos sí vienen. Ese único mes se interpola linealmente y queda marcado (`imputed`); un hueco de más de un mes levanta un error en vez de inventarse.

## Hallazgos

### 1. El alivio del COVID fue grande y se revirtió por completo

| Régimen | Total sistema (promedio) | Comercial | Consumo | Vivienda |
|---|---|---|---|---|
| Pre-COVID (2016-01 → 2020-02) | 1,94% | 1,67% | 1,99% | 2,48% |
| Alivio COVID (2020-03 → 2021-12) | 1,65% | 1,73% | 1,46% | 1,60% |
| Normalización (2022-01 →) | 2,14% | 2,30% | 2,18% | 1,94% |

La mora del sistema era **2,04% en febrero de 2020**, cayó a un mínimo de **1,26% en diciembre de 2021** (−0,78 pp) y está en **2,44% en agosto de 2026**: un rebote de **+1,18 pp**, que termina **0,40 pp por sobre el punto de partida**. Las carteras no se movieron juntas. El crédito a hogares osciló mucho más que el comercial:

| Cartera | Feb 2020 | Mínimo | Ago 2026 | Caída hasta el mínimo | Rebote desde entonces |
|---|---|---|---|---|---|
| Comercial | 1,90% | 1,42% (2021-12) | 2,34% | −0,47 pp | +0,92 pp |
| Consumo | 2,17% | 0,98% (2021-10) | 2,35% | −1,18 pp | +1,36 pp |
| Vivienda | 2,30% | 1,04% (2022-03) | 2,65% | −1,26 pp | +1,61 pp |

La mora hipotecaria es hoy la más alejada de su nivel pre-COVID entre las carteras de hogares (+0,35 pp, contra +0,18 pp de consumo), y la comercial muestra la mayor brecha frente a febrero de 2020 de las tres (+0,45 pp), aunque fue la que menos osciló.

### 2. El alza desde el mínimo es deterioro dentro de los bancos, no un cambio de quién presta

Descomponiendo el cambio de +1,25 pp entre diciembre de 2021 y agosto de 2026 en cambio *dentro de cada banco* y cambio de *mezcla* (Kitagawa, sobre los 11 bancos presentes en ambas fechas, que cubren entre 96 y 99,7% de las colocaciones):

| Componente | pp |
|---|---|
| Deterioro dentro de los bancos | **+1,27** |
| Mezcla (cambios de participación de mercado) | −0,02 |
| Total | +1,25 |

Tres bancos explican cerca de dos tercios: **Santander-Chile (+0,36 pp), Banco del Estado (+0,33 pp) y Scotiabank Chile (+0,17 pp)**.

![Aporte por banco](reports/figures/02_aporte_bancos.png)

### 3. Los bancos convergen en una crisis y divergen en una recuperación

La dispersión entre bancos en mora de consumo (rango intercuartil) tuvo su máximo de **2,14 pp en julio de 2024** y hoy es de **0,42 pp**. El *orden* de los bancos es moderadamente persistente: la correlación de rangos de Spearman de la mora de consumo entre diciembre de 2019 y agosto de 2026 es **0,69**.

![Dispersión entre bancos](reports/figures/03_dispersion_consumo.png)

![Mapa de calor por banco y año](reports/figures/05_mapa_calor_bancos.png)

### 4. Ganarle a "igual que hoy" es difícil, y la evidencia es escasa

Backtest con origen móvil sobre el total del sistema (primer pronóstico tras 60 meses de historia, 68 orígenes al horizonte de 1 mes). Métrica: MAE relativo al pronóstico ingenuo (1,0 = igual que el ingenuo), con intervalo de 95% por bootstrap de bloques.

| Horizonte | ARIMA(1,1,1) | ETS amortiguado | Deriva 24 meses |
|---|---|---|---|
| 1 mes | 0,94 [0,87; 1,02] | 0,98 [0,88; 1,08] | 1,04 [0,90; 1,22] |
| 3 meses | **0,83 [0,73; 0,95]** | 0,85 [0,71; 1,00] | 1,05 [0,79; 1,37] |
| 6 meses | 0,88 [0,75; 1,03] | 0,87 [0,70; 1,06] | 1,12 [0,72; 1,64] |
| 12 meses | 0,94 [0,83; 1,14] | 0,91 [0,77; 1,15] | 1,39 [0,89; 2,63] |

**Solo ARIMA a 3 meses tiene un intervalo que excluye el 1.** En el resto no puedo demostrar ventaja sobre el ingenuo, y extrapolar la tendencia reciente (deriva) es *peor* en horizontes largos. El pronóstico estacional ingenuo es mucho peor (rMAE 8,4 a 1 mes): la mora no tiene una estacionalidad estable.

![Backtest](reports/figures/04_backtest_rmae.png)

### 5. Los indicadores macro no mejoran el pronóstico

Probé tres indicadores mensuales: desempleo, tasa de política monetaria e IMACEC (variación anual). El desempleo y el IMACEC se rezagan un mes por publicación, de modo que un pronóstico solo usa lo que se sabía en su origen.

**Sí se mueven antes que la mora, con signos que requieren cuidado.** Correlación entre el cambio a 12 meses de la mora y el cambio a 12 meses de cada indicador, con el indicador adelantado *k* meses (116 observaciones solapadas):

| Indicador | Mismo mes | Adelantado 6 meses | Adelantado 12 meses |
|---|---|---|---|
| Tasa de política monetaria (TPM) | −0,14 | +0,39 | **+0,67** |
| Desempleo | +0,16 | −0,27 | **−0,51** |
| IMACEC (variación anual) | −0,40 | −0,34 | −0,11 |

![Correlaciones rezagadas](reports/figures/06_macro_rezagos.png)

- La tasa de política monetaria, un año antes, se correlaciona fuerte con el alza de la mora: consistente con que las alzas de tasa se traspasan a los deudores, lo que no probé como afirmación causal.
- El desempleo tiene el signo *equivocado* en los rezagos largos. El desempleo subió con fuerza en 2020 mientras la mora caía, por las medidas de alivio, y ese episodio domina una muestra tan corta.
- Son cambios sobre ventanas de 12 meses solapadas, así que las correlaciones vecinas no son independientes y no doy p-valores. Es una descripción, no una prueba.

**Pero agregarlos empeora los pronósticos.** Pronósticos directos a cada horizonte (mínimos cuadrados del cambio futuro sobre las features de hoy), con el mismo protocolo de origen móvil del hallazgo 4 (68 orígenes a un mes). La referencia es el mismo modelo sin macro, así que la tabla aísla lo que aportan los indicadores. Menos de 1 es mejor.

| Horizonte | Solo momentum, vs ingenuo | + desempleo, vs solo momentum | + desempleo, TPM e IMACEC, vs solo momentum |
|---|---|---|---|
| 1 mes | 0,95 [0,87; 1,06] | 1,11 [1,01; 1,21] | 1,14 [1,03; 1,27] |
| 3 meses | **0,82 [0,70; 0,97]** | 1,24 [1,04; 1,47] | 1,30 [0,99; 1,70] |
| 6 meses | 0,98 [0,80; 1,13] | 1,22 [0,97; 1,47] | 1,21 [0,73; 1,95] |
| 12 meses | 1,13 [1,02; 1,28] | 1,12 [0,89; 1,24] | 1,10 [0,61; 1,91] |

![Aporte de agregar indicadores macro](reports/figures/07_macro_aporte.png)

- Agregar macro sube el error entre 10 y 30% respecto de usar solo el momentum. A 1 y 3 meses con desempleo, y a 1 mes con los tres indicadores, el intervalo excluye el 1: es peor, no solo "no mejor". En el resto los intervalos incluyen el 1.
- El momentum solo (el cambio de los últimos tres meses) le gana al ingenuo únicamente a 3 meses (0,82, casi igual que el ARIMA del hallazgo 4) y es *peor* que el ingenuo a 12 meses.
- **No probé por qué el macro perjudica.** Una causa plausible es que en las ventanas de entrenamiento el alivio del COVID invirtió el vínculo habitual entre desempleo y mora, así que los coeficientes aprendidos ahí inducen a error después; la fila de desempleo de la tabla de correlaciones es el síntoma. Con 60 a 120 meses, tres regresores adicionales también pueden simplemente sobreajustar.

## Limitaciones

- **Mora no es pérdida.** La mora a 90+ días no dice nada sobre recuperaciones, provisiones ni castigos.
- **La atribución del hallazgo 2 es contable, no causal.** Dice *dónde* ocurrió el alza, no por qué. Las medidas de alivio de 2020–21 son contexto que no puse a prueba.
- **Los saldos de colocaciones son implícitos, no publicados.** La CMF entrega la mora en % y en MM$, pero no el stock de colocaciones, así que lo despejo como `MM$ / (% / 100)`. Solo está definido donde la mora es positiva, por lo que los bancos con 0% salen de los ponderadores. Por eso el valor reconstruido del sistema en la descomposición (2,49%) queda algo sobre el oficial (2,44%).
- **Backtest pequeño.** 56–68 orígenes solapados sobre una sola serie con cambios de régimen. Los intervalos son anchos y la ventana de evaluación parte en 2021, así que mide sobre todo el rebote posterior al COVID.
- **Las historias de las entidades no son del todo comparables.** Los nombres cambian en la fuente (Itaú Corpbanca → Banco Itaú Chile, BBVA Chile → Scotiabank Azul), la serie BBVA/Scotiabank Azul termina en 2018-08 y Banco Security deja de reportarse después de 2025-10. Manejo los cambios de nombre que pude identificar en los archivos; no investigué las operaciones societarias detrás de ellos.
- **Los datos macro no son versiones en tiempo real.** Vienen de un agregador de terceros y son los valores disponibles en la fecha de descarga; revisiones posteriores no se verían. El rezago de publicación de un mes que aplico al desempleo y al IMACEC es un supuesto que no verifiqué contra los calendarios oficiales, y solo probé modelos lineales.

## Cómo correrlo

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=src                                # PowerShell: $env:PYTHONPATH="src"

python -m cmf_delinquency.pipeline --offline         # usa el panel versionado, ~30 s
python -m cmf_delinquency.pipeline                   # descarga primero los 128 archivos y las series macro
pytest                                               # 64 tests, sin red
```

Salidas: `reports/results.json`, `reports/tables/*.csv`, `reports/figures/*.png`.

## Estructura

```
src/cmf_delinquency/
  download.py   lee la página índice y baja los .xlsx mensuales (idempotente)
  parse.py      tres formatos -> un panel limpio, alias de nombres, fusiones
  analysis.py   regímenes, descomposición dentro/mezcla, dispersión, persistencia de rangos
  macro.py      indicadores macro abiertos (mindicador.cl) y rezagos de publicación
  forecast.py   backtest con origen móvil, intervalos por bootstrap de bloques
  plots.py      figuras
  pipeline.py   de punta a punta
tests/          64 tests: archivos sintéticos en ambos formatos + chequeos de integridad sobre el panel real + chequeos macro y de no mirar hacia adelante
```

## Licencia

MIT. Los datos de origen pertenecen a la Comisión para el Mercado Financiero (CMF).
