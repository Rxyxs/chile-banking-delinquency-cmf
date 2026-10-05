"""La pagina de GitHub Pages se genera desde el panel y results.json. Sin red ni navegador."""
import json
import re
from pathlib import Path

import pytest

from cmf_delinquency import site

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = re.compile(r'<script type="application/json" id="data">(.*?)</script>', re.S)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    docs = tmp_path_factory.mktemp("docs")
    out = site.build_site(docs_dir=docs)
    html = out.read_text(encoding="utf-8")
    return docs, html, json.loads(PAYLOAD.search(html).group(1).replace("<\\/", "</"))


def test_the_page_is_written_with_its_assets(built):
    docs, html, _ = built
    assert (docs / "index.html").exists() and (docs / ".nojekyll").exists()
    assert {p.name for p in (docs / "figures").glob("*.png")} >= {"07_macro_aporte.png", "08_bancos_modelos.png"}
    assert "__DATA__" not in html


def test_embedded_data_is_strict_json(built):
    _, html, _ = built
    raw = PAYLOAD.search(html).group(1)
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw.replace("<\\/", "</"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


def test_every_series_is_aligned_with_the_months(built):
    _, _, data = built
    n = len(data["months"])
    assert n == 128 and data["months"][0] == "2016-01" and data["months"][-1] == "2026-08"
    for series in data["system"].values():
        assert len(series) == n and None not in series
    for bank in data["banks"].values():
        assert all(len(v) == n for v in bank.values())


def test_the_imputed_month_is_marked(built):
    _, _, data = built
    assert [data["months"][i] for i in data["imputed_idx"]] == ["2023-07"]


def test_regimes_cover_the_whole_period_without_gaps(built):
    _, _, data = built
    r = data["regimes"]
    assert r[0]["i0"] == 0 and r[-1]["i1"] == len(data["months"]) - 1
    assert all(a["i1"] + 1 == b["i0"] for a, b in zip(r, r[1:]))
    assert data["months"][r[1]["i0"]] == "2020-03" and data["months"][r[1]["i1"]] == "2021-12"


def test_bank_explorer_has_a_valid_default(built):
    _, _, data = built
    assert data["default_bank"] in data["bank_names"] == sorted(data["banks"])
    assert len(data["bank_names"]) >= 20


def test_key_numbers_come_from_the_results_file(built):
    _, _, data = built
    results = json.loads((ROOT / "reports" / "results.json").read_text(encoding="utf-8"))
    assert data["key"]["feb2020"] == round(results["covid"]["mora_feb_2020"], 2)
    assert data["key"]["last"] == round(results["covid"]["ultimo"], 2)
    assert data["key"]["last_month"] == results["covid"]["ultimo_mes"]
    assert data["key"]["within"] > 1.0 > abs(data["key"]["mix"])


def test_forecast_tables_have_every_model_and_horizon(built):
    _, _, data = built
    for name, models in {"system": {"arima_111", "ets_damped", "drift"},
                         "macro": {"momentum+unemployment", "momentum+macro"},
                         "banks": {"ets_damped", "pooled_gap", "pooled_system"}}.items():
        rows = data["forecast"][name]
        assert {r["model"] for r in rows} == models
        assert {r["h"] for r in rows} == {1, 3, 6, 12}
        assert len(rows) == len(models) * 4


def test_page_figures_match_the_readme(built):
    """El README y la pagina cuentan lo mismo: cada cifra de las tablas debe aparecer en el README."""
    _, _, data = built
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checks = [("system", "rmae"), ("macro", "vs_momentum"), ("banks", "vs_naive")]
    for table, key in checks:
        for row in data["forecast"][table]:
            assert f"{row[key]:.2f}" in readme, (table, row["model"], row["h"], row[key])


def test_rounding_is_decided_in_python_not_by_the_browser():
    assert site._r2({"x": 1.3049999999999999, "m": "a"}) == {"x": 1.3, "m": "a"}
    assert site._r2({"x": float("nan")})["x"] != site._r2({"x": float("nan")})["x"]  # NaN se conserva, no se inventa


def test_a_closing_script_tag_inside_the_data_cannot_break_the_page():
    html = site.render({"bank": "</script><script>alert(1)</script>"})
    payload = PAYLOAD.search(html).group(1)
    assert "</" not in payload and "<\\/script>" in payload


def test_the_page_has_no_external_scripts_or_styles():
    html = site.TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r'<script[^>]+src="https?://', html)
    assert not re.search(r'<link[^>]+href="https?://', html)


def test_the_page_is_accessible_by_keyboard_and_has_a_table_view():
    html = site.TEMPLATE.read_text(encoding="utf-8")
    assert 'tabindex' in html and "ArrowLeft" in html and "view_table" in html
