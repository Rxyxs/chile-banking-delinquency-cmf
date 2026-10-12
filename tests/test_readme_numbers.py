"""Las cifras de los hallazgos 7 y 8 del README salen de reports/results.json, en ambos idiomas.

Si el pipeline cambia un resultado y el README no se actualiza, este test falla.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = json.loads((ROOT / "reports" / "results.json").read_text(encoding="utf-8"))
README = {"en": (ROOT / "README.md").read_text(encoding="utf-8"), "es": (ROOT / "README.es.md").read_text(encoding="utf-8")}


def fmt(x: float, lang: str, digits: int = 2) -> str:
    s = f"{abs(x):.{digits}f}"
    s = s.replace(".", ",") if lang == "es" else s
    return ("−" if x < 0 else "") + s


def claims() -> list[tuple[str, float, int]]:
    st = RESULTS["estres"]
    rob = st["robustez_consumo"]
    ml = {(r["cartera"], r["model"], r["h"]): r for r in RESULTS["ml"]["backtest"]}
    no_covid = {(r["cartera"], r["model"], r["h"]): r for r in RESULTS["ml"]["sin_covid_en_entrenamiento"]}
    bank_val = {(r["mode"], r["bank"]): r["rmae"] for r in st["validacion_por_banco"]}
    out = [(f"validacion {p}", v["rmae"], 2) for p, v in st["validacion_condicional"].items()]
    out += [
        ("rezago fijo 6 consumo", st["sensibilidad_rezago"]["consumo"]["rezago_6"], 2),
        ("desempleo con covid", rob["con_covid"]["d_unemployment_pp"], 2),
        ("t desempleo con covid", rob["con_covid"]["t_d_unemployment_pp"], 1),
        ("tpm pre covid", rob["pre_covid"]["d_tpm_pp"], 2),
        ("tpm post 2021", rob["post_2021"]["d_tpm_pp"], 2),
        ("lightgbm consumo h6", ml[("consumo", "lightgbm", 6)]["rmae"], 2),
        ("lightgbm total h6", ml[("total", "lightgbm", 6)]["rmae"], 2),
        ("lightgbm sin covid consumo h6", no_covid[("consumo", "lightgbm", 6)]["rmae"], 2),
        ("banco macro propio", bank_val[("macro_propio", "Todos")], 2),
        ("banco dos etapas", bank_val[("dos_etapas", "Todos")], 2),
        ("banco oraculo", bank_val[("dos_etapas_oraculo", "Todos")], 2),
    ]
    return out


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize("name,value,digits", claims())
def test_readme_quotes_the_pipeline(lang, name, value, digits):
    assert fmt(value, lang, digits) in README[lang], f"{name}: {fmt(value, lang, digits)} no aparece en el README ({lang})"


def test_robustness_supports_the_modelling_decisions():
    rob = RESULTS["estres"]["robustez_consumo"]
    assert rob["con_covid"]["d_unemployment_pp"] < 0  # el signo perverso que justifica excluir el COVID
    assert rob["pre_covid"]["d_tpm_pp"] > 0 and rob["post_2021"]["d_tpm_pp"] > 0  # la TPM empuja en ambas submuestras
