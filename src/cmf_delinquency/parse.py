"""Lee los .xlsx mensuales de la CMF y los unifica en un panel banco x mes.

El archivo cambió de formato tres veces entre 2016 y 2026:

* ``antiguo``  (2016-01 a 2021-12): 9 columnas, el nombre del banco está en la columna 0.
* ``medio``    (2022-01 a 2023-03): 12 columnas, banco en la columna 1, sin encabezado visible.
* ``nuevo``    (2023-04 en adelante): igual que el medio pero con encabezados de texto.

Las columnas lógicas son las mismas en los tres: colocaciones totales, créditos a
clientes, comerciales, personas, consumo y vivienda (todas en % de morosidad 90+ días),
más el monto en MM$ de la cartera morosa total.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

PORTFOLIOS = ["total", "clientes", "comercial", "personas", "consumo", "vivienda"]

# (columna del banco, columnas de los 6 porcentajes, columna del monto MM$)
LAYOUTS = {
    "antiguo": (0, [1, 2, 3, 4, 5, 6], 8),
    "nuevo": (1, [2, 3, 4, 5, 6, 7], 10),
}

SYSTEM_NAME = "Sistema Bancario"

# Fusiones y cambios de nombre. La clave es el nombre tal como aparece en el archivo.
BANK_ALIASES = {
    "Itaú Corpbanca": "Banco Itaú Chile",
    "Jp Morgan Chase Bank, N.A.": "JP Morgan Chase Bank, N.A.",
    "Banco Bilbao Vizcaya Argentaria, Chile": "BBVA Chile / Scotiabank Azul",
    "Scotiabank Azul": "BBVA Chile / Scotiabank Azul",
    "The Bank of Tokyo-Mitsubishi UFJ, Ltd.": "MUFG Bank",
    "MUFG Bank, Ltd.": "MUFG Bank",
}

# En 2016-01 a 2016-03 "Banco Itaú Chile" es la entidad previa a la fusión con
# Corpbanca (que desde 2016-04 se publica como "Itaú Corpbanca"). No es la misma serie.
PRE_MERGE_ITAU_END = pd.Timestamp("2016-03-01")


def _is_value(v: object) -> bool:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return False
    if isinstance(v, (int, float, np.integer, np.floating)):
        return True
    return str(v).strip() in {"---", "--", "-"}


def _to_float(v: object) -> float:
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    return np.nan  # '---' = no aplica (el banco no tiene esa cartera)


def detect_layout(df: pd.DataFrame) -> str:
    """Identifica el formato del archivo y verifica que los encabezados coincidan."""
    layout = "antiguo" if df.shape[1] == 9 else "nuevo"
    bank_col, value_cols, _ = LAYOUTS[layout]
    expected = {"comerciales": value_cols[2], "consumo": value_cols[4], "vivienda": value_cols[5]}
    head = df.iloc[:16].astype(str).apply(lambda col: col.str.lower())
    # El formato medio no trae encabezados de texto para el bloque de porcentajes; se
    # acepta si la columna de banco contiene filas de datos en la posición esperada.
    if layout == "nuevo" and not head.apply(lambda c: c.str.contains("comerciales")).any().any():
        return layout
    for word, col in expected.items():
        if not head.iloc[:, col].str.contains(word).any():
            raise ValueError(f"Formato no reconocido: no hay '{word}' en la columna {col}")
    return layout


def parse_file(path: Path) -> pd.DataFrame:
    """Devuelve una fila por banco (y una para el sistema) con los % de mora por cartera."""
    month = pd.Timestamp(f"{path.stem}-01")
    df = pd.read_excel(path, header=None)
    layout = detect_layout(df)
    bank_col, value_cols, mm_col = LAYOUTS[layout]

    rows = []
    for i in range(len(df)):
        name = df.iat[i, bank_col]
        if not isinstance(name, str) or not _is_value(df.iat[i, value_cols[0]]):
            continue
        clean = re.sub(r"\s+", " ", name).strip()
        record = {"date": month, "bank_raw": clean, "layout": layout}
        for port, col in zip(PORTFOLIOS, value_cols):
            record[port] = _to_float(df.iat[i, col])
        record["mora90_mm"] = _to_float(df.iat[i, mm_col]) if mm_col < df.shape[1] else np.nan
        rows.append(record)
        if clean == SYSTEM_NAME:
            break  # lo que sigue son notas al pie
    if not rows or rows[-1]["bank_raw"] != SYSTEM_NAME:
        raise ValueError(f"{path.name}: no se encontró la fila '{SYSTEM_NAME}'")
    return pd.DataFrame(rows)


def canonical_bank(row_name: str, month: pd.Timestamp) -> str | None:
    """Nombre canónico del banco; ``None`` si la fila no pertenece a ninguna serie continua."""
    if row_name == "Banco Itaú Chile" and month <= PRE_MERGE_ITAU_END:
        return None
    return BANK_ALIASES.get(row_name, row_name)


def build_panel(raw_dir: Path) -> pd.DataFrame:
    """Panel completo: una fila por (mes, banco) con las seis carteras."""
    frames = [parse_file(p) for p in sorted(Path(raw_dir).glob("*.xlsx"))]
    if not frames:
        raise FileNotFoundError(f"No hay .xlsx en {raw_dir}")
    panel = pd.concat(frames, ignore_index=True)
    panel["bank"] = [canonical_bank(n, m) for n, m in zip(panel["bank_raw"], panel["date"])]
    panel = panel.dropna(subset=["bank"])
    panel["is_system"] = panel["bank"] == SYSTEM_NAME
    cols = ["date", "bank", "is_system", *PORTFOLIOS, "mora90_mm", "bank_raw", "layout"]
    panel = panel[cols].sort_values(["date", "is_system", "bank"]).reset_index(drop=True)
    dup = panel.duplicated(["date", "bank"]).sum()
    if dup:
        raise ValueError(f"{dup} filas duplicadas (date, bank) tras normalizar nombres")
    return panel


if __name__ == "__main__":
    out = build_panel(Path("data/raw"))
    Path("data").mkdir(exist_ok=True)
    out.to_csv("data/panel_mora90.csv", index=False)
    print(f"{len(out)} filas | {out['bank'].nunique()} entidades | {out['date'].min():%Y-%m} -> {out['date'].max():%Y-%m}")
