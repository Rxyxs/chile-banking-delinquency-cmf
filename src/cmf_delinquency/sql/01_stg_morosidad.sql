-- staging: panel CMF tal como se versiona (una fila por banco y mes, mora en %).
CREATE OR REPLACE TABLE stg_morosidad AS
SELECT
    CAST(date AS DATE)          AS month,
    bank,
    CAST(is_system AS BOOLEAN)  AS is_system,
    total, clientes, comercial, personas, consumo, vivienda,
    mora90_mm,
    bank_raw,
    layout
FROM read_csv_auto('{panel_csv}', header = true);
