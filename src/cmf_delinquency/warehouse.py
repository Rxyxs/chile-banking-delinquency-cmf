"""Almacen analitico en DuckDB (``warehouse/delinquency.duckdb``) construido desde los CSV versionados.

Los modelos SQL viven en ``sql/`` y se ejecutan en orden de nombre, por capas al estilo dbt:

* ``stg_*``  : staging, los CSV con tipos explicitos.
* ``dim_*``  : dimensiones (una fila por banco).
* ``fct_*``  : hechos (banco x mes, con colocaciones implicitas y peso en el sistema).
* ``mart_*`` : tablas listas para analisis (sistema + macro con los factores del modelo de estres).

Cada construccion reemplaza las tablas (``CREATE OR REPLACE``): es idempotente y siempre refleja el
CSV actual. Al final corren pruebas de calidad; si alguna falla se levanta un error.

Uso:
    python -m cmf_delinquency.warehouse
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = Path(__file__).resolve().parent / "sql"
DB_PATH = ROOT / "warehouse" / "delinquency.duckdb"
PANEL_CSV = ROOT / "data" / "panel_mora90.csv"
MACRO_CSV = ROOT / "data" / "macro_indicators.csv"

# Cada prueba es una consulta que debe devolver 0 filas.
QUALITY_TESTS = {
    "panel sin duplicados banco-mes": "SELECT month, bank FROM stg_morosidad GROUP BY ALL HAVING count(*) > 1",
    "mora entre 0 y 100": "SELECT * FROM stg_morosidad WHERE total < 0 OR total > 100",
    "una fila del sistema por mes": (
        "SELECT month FROM stg_morosidad GROUP BY month HAVING count(*) FILTER (WHERE is_system) <> 1"
    ),
    "pesos de colocaciones suman 1": (
        "SELECT month FROM fct_mora_banco_mes GROUP BY month HAVING abs(sum(loan_share) - 1) > 1e-6"
    ),
    "macro sin meses duplicados": "SELECT month FROM stg_macro GROUP BY month HAVING count(*) > 1",
}


def models(sql_dir: Path = SQL_DIR) -> list[Path]:
    return sorted(sql_dir.glob("*.sql"))


def run_quality_tests(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Devuelve el numero de filas que viola cada prueba (0 = pasa)."""
    return {name: len(con.execute(q).fetchall()) for name, q in QUALITY_TESTS.items()}


def build_warehouse(db_path: Path = DB_PATH, panel_csv: Path = PANEL_CSV, macro_csv: Path = MACRO_CSV) -> dict[str, int]:
    """Construye (o reconstruye) el almacen y devuelve el numero de filas de cada tabla."""
    for path in (panel_csv, macro_csv):
        if not path.exists():
            raise FileNotFoundError(f"Falta {path}; corre primero `python -m cmf_delinquency.pipeline`")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    params = {"panel_csv": panel_csv.resolve().as_posix(), "macro_csv": macro_csv.resolve().as_posix()}
    with duckdb.connect(str(db_path)) as con:
        tables = []
        for model in models():
            con.execute(model.read_text(encoding="utf-8").format(**params))
            tables.append(model.stem.split("_", 1)[1])
        failures = {k: v for k, v in run_quality_tests(con).items() if v}
        if failures:
            raise ValueError(f"Fallan pruebas de calidad del almacen: {failures}")
        return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def query(sql: str, db_path: Path = DB_PATH):
    """Consulta de solo lectura al almacen; devuelve un DataFrame."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql).df()


if __name__ == "__main__":
    counts = build_warehouse()
    print(f"Almacen en {DB_PATH.relative_to(ROOT)}")
    for table, n in counts.items():
        print(f"  {table:<24} {n:>6} filas")
    print("Pruebas de calidad: todas pasan")
