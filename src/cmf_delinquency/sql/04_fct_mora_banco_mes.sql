-- hecho: mora por banco y mes con colocaciones implicitas (mora MM$ / mora %) y peso en el sistema.
CREATE OR REPLACE TABLE fct_mora_banco_mes AS
WITH loans AS (
    SELECT
        *,
        CASE WHEN total > 0 THEN mora90_mm / (total / 100.0) END AS loans_mm
    FROM stg_morosidad
    WHERE NOT is_system
)
SELECT
    month, bank, total, comercial, consumo, vivienda, mora90_mm, loans_mm,
    loans_mm / sum(loans_mm) OVER (PARTITION BY month) AS loan_share
FROM loans;
