-- staging: desempleo, TPM e IMACEC mensuales (mindicador.cl).
CREATE OR REPLACE TABLE stg_macro AS
SELECT
    CAST(month AS DATE) AS month,
    unemployment_pct,
    tpm_pct,
    imacec_yoy_pct
FROM read_csv_auto('{macro_csv}', header = true);
