-- dimension: un registro por entidad, con su primer y ultimo mes publicado.
CREATE OR REPLACE TABLE dim_banco AS
SELECT
    bank,
    bool_or(is_system)            AS is_system,
    min(month)                    AS first_month,
    max(month)                    AS last_month,
    count(*)                      AS months_reported,
    arg_max(bank_raw, month)      AS latest_raw_name
FROM stg_morosidad
GROUP BY bank;
