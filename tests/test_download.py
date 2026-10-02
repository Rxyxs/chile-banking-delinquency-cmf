from datetime import date

from cmf_delinquency.download import _is_xlsx, parse_index

HTML = """
<a href="articles-113888_recurso_1.xlsx?ts=1" class="card-img" aria-label="Descargar Agosto 2026 (xlsx, se abre en nueva ventana)">
<a href="articles-27123_recurso_1.xlsx?ts=2" class="card-img" aria-label="Descargar abril 2019 (xlsx, se abre en nueva ventana)">
<a href="articles-1_recurso_1.xlsx?ts=3" class="card-img" aria-label="Descargar Setiembre 2017 (xlsx, se abre en nueva ventana)">
<a href="articles-9_recurso_1.pdf?ts=4" aria-label="Descargar Enero 2018 (pdf)">
<a href="articles-5_recurso_1.xlsx?ts=5" aria-label="Descargar Informe anual (xlsx, se abre en nueva ventana)">
"""


def test_parse_index_reads_months_in_any_case():
    idx = parse_index(HTML)
    assert idx[date(2026, 8, 1)] == "articles-113888_recurso_1.xlsx"
    assert idx[date(2019, 4, 1)] == "articles-27123_recurso_1.xlsx"


def test_parse_index_accepts_setiembre_spelling():
    assert date(2017, 9, 1) in parse_index(HTML)


def test_parse_index_ignores_non_month_links():
    assert len(parse_index(HTML)) == 3


def test_is_xlsx(tmp_path):
    good = tmp_path / "a.xlsx"
    good.write_bytes(b"PK" + b"\x00" * 2000)
    html_error = tmp_path / "b.xlsx"
    html_error.write_bytes(b"<html>403 Forbidden</html>")
    assert _is_xlsx(good)
    assert not _is_xlsx(html_error)
    assert not _is_xlsx(tmp_path / "missing.xlsx")
