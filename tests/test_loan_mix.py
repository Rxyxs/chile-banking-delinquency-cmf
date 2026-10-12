"""Composicion de cartera por banco (Reporte Financiero Mensual): parser de ambos formatos y la prueba
de si explica la sensibilidad a la TPM. Sin red: archivos sinteticos con los encabezados reales."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmf_delinquency import banks as B

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, layout: str) -> Path:
    """Hoja 'Activos Bancos 2' minima con los encabezados de cada formato."""
    grid = [[None] * 26 for _ in range(16)]
    if layout == "antiguo":
        name, com, cons, card, viv = 0, 13, 17, 19, 22
        grid[6][name] = "Instituciones"
        grid[8][com] = "Colocaciones comerciales"
        grid[9][cons] = "Consumo (1)"
        grid[10][card] = "Tarjetas de crédito"
        grid[9][viv] = "Vivienda (1)"
    else:
        name, com, cons, card, viv = 1, 2, 7, 9, 11
        grid[6][name] = "Instituciones (*)"
        grid[7][com] = "Comerciales (1)"
        grid[8][cons] = "Consumo (1)"
        grid[9][card] = "Deudores por Tarjetas de crédito"
        grid[8][viv] = "Vivienda (1)"
    rows = [("Banco A", 800, 100, 40, 100), ("Banco B", 100, 600, 300, 300), ("Sistema Bancario", 900, 700, 340, 400)]
    for i, (bank, c, k, t, v) in enumerate(rows):
        row = grid[12 + i]
        row[name], row[com], row[cons], row[card], row[viv] = bank, c, k, t, v
    with pd.ExcelWriter(path) as xl:
        pd.DataFrame(grid).to_excel(xl, sheet_name=B.RFM_SHEET, header=False, index=False)
    return path


@pytest.mark.parametrize("layout", ["antiguo", "nuevo"])
def test_parse_loan_mix_reads_both_layouts(tmp_path, layout):
    mix = B.parse_loan_mix(_write(tmp_path / f"{layout}.xlsx", layout), "2024-12")
    assert list(mix["bank_raw"]) == ["Banco A", "Banco B"]  # la fila del sistema se descarta
    a = mix.set_index("bank_raw").loc["Banco A"]
    assert a["loans_mm"] == 1000 and a["consumo_share"] == pytest.approx(0.10)
    assert a["tarjetas_share_consumo"] == pytest.approx(0.40)


def test_missing_header_fails_loudly(tmp_path):
    path = tmp_path / "x.xlsx"
    with pd.ExcelWriter(path) as xl:
        pd.DataFrame([["nada"]]).to_excel(xl, sheet_name=B.RFM_SHEET, header=False, index=False)
    with pytest.raises(ValueError, match="No se encontro"):
        B.parse_loan_mix(path, "2024-12")


def test_rfm_candidates_keep_page_order():
    html = ('<a href="articles-1_recurso_1.xlsx" x aria-label="Descargar Diciembre 2019 (xlsx">'
            '<a href="articles-2_recurso_1.xlsx" x aria-label="Descargar Diciembre 2019 (xlsx">')
    assert B.rfm_candidates(html) == {"2019-12": ["articles-1_recurso_1.xlsx", "articles-2_recurso_1.xlsx"]}


def test_explain_sensitivity_detects_a_monotone_link_and_not_noise():
    banks = [f"b{i}" for i in range(10)]
    sens = pd.DataFrame({"beta_tpm": np.arange(10.0), "mora_actual": 1.0}, index=banks)
    prof = pd.DataFrame({"consumo_share": np.arange(10.0),
                         "tarjetas_share_consumo": np.random.default_rng(0).permutation(10).astype(float)}, index=banks)
    out = B.explain_sensitivity(sens, prof, features=("consumo_share", "tarjetas_share_consumo"))
    assert out.loc["consumo_share", "spearman"] == pytest.approx(1.0)
    assert out.loc["consumo_share", "p_permutacion"] < 0.01
    assert out.loc["tarjetas_share_consumo", "p_permutacion"] > out.loc["consumo_share", "p_permutacion"]


def test_versioned_loan_mix_covers_the_rate_sensitive_banks():
    mix = pd.read_csv(ROOT / "data" / "loan_mix.csv")
    profile = B.loan_mix_profile(mix)
    for bank in ("Banco del Estado de Chile", "Banco de Crédito e Inversiones", "Banco Bice", "Banco Consorcio"):
        assert 0 < profile.loc[bank, "consumo_share"] < 1
    assert (mix["consumo_mm"] <= mix["loans_mm"]).all()
    assert (mix["tarjetas_mm"].fillna(0) <= mix["consumo_mm"] + 1e-6).all()
