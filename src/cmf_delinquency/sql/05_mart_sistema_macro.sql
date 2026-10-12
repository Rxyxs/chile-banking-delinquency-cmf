-- mart: serie del sistema unida a la macro, con los factores del modelo satelite
-- (cambios a 12 meses y rezago de 6 meses). Los meses sin dato del sistema quedan en NULL:
-- la imputacion de un mes faltante la hace la capa de Python, no el almacen.
CREATE OR REPLACE TABLE mart_sistema_macro AS
WITH months AS (
    SELECT CAST(m AS DATE) AS month
    FROM range((SELECT min(month) FROM stg_macro), (SELECT max(month) FROM stg_macro) + INTERVAL 1 MONTH, INTERVAL 1 MONTH) t(m)
),
sys AS (
    SELECT month, total, comercial, consumo, vivienda, mora90_mm / (total / 100.0) AS loans_mm
    FROM stg_morosidad
    WHERE is_system AND total IS NOT NULL
),
changes AS (
    SELECT
        m.month, s.total, s.comercial, s.consumo, s.vivienda, s.loans_mm,
        x.unemployment_pct, x.tpm_pct, x.imacec_yoy_pct,
        s.total - lag(s.total, 12) OVER w                         AS d12_total_pp,
        s.consumo - lag(s.consumo, 12) OVER w                     AS d12_consumo_pp,
        x.tpm_pct - lag(x.tpm_pct, 12) OVER w                     AS d12_tpm_pp,
        x.unemployment_pct - lag(x.unemployment_pct, 12) OVER w   AS d12_unemployment_pp
    FROM months m
    LEFT JOIN sys s USING (month)
    LEFT JOIN stg_macro x USING (month)
    WINDOW w AS (ORDER BY m.month)
)
SELECT
    *,
    lag(d12_tpm_pp, 6) OVER w           AS d_tpm_pp_lag6,
    lag(d12_unemployment_pp, 6) OVER w  AS d_unemployment_pp_lag6,
    lag(imacec_yoy_pct, 6) OVER w       AS imacec_yoy_pct_lag6,
    month BETWEEN DATE '2020-03-01' AND DATE '2021-12-01' AS covid_relief
FROM changes
WINDOW w AS (ORDER BY month)
ORDER BY month;
