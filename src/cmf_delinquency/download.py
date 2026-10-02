"""Descarga los archivos mensuales de morosidad 90+ días publicados por la CMF.

La CMF publica un .xlsx por mes en una sola página de estadísticas. No requiere
clave ni formulario: se leen los enlaces de la página y se baja cada archivo.
"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

import requests

BASE_URL = "https://www.cmfchile.cl/portal/estadisticas/626/"
INDEX_URL = BASE_URL + "w4-propertyvalue-28914.html"
USER_AGENT = "Mozilla/5.0 (compatible; chile-banking-delinquency-cmf)"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_LINK_RE = re.compile(
    r'<a href="(articles-\d+_recurso_1\.xlsx)[^"]*"[^>]*aria-label="Descargar ([^"(]+?) \(xlsx'
)


def parse_index(html: str) -> dict[date, str]:
    """Devuelve {primer día del mes: nombre del archivo} a partir del HTML del índice."""
    out: dict[date, str] = {}
    for filename, label in _LINK_RE.findall(html):
        mes, _, anio = label.strip().lower().partition(" ")
        if mes not in MESES or not anio.strip().isdigit():
            continue
        out[date(int(anio), MESES[mes], 1)] = filename
    return out


def _is_xlsx(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1000:
        return False
    with path.open("rb") as fh:
        return fh.read(2) == b"PK"


def fetch_index(session: requests.Session | None = None) -> dict[date, str]:
    s = session or requests.Session()
    resp = s.get(INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    index = parse_index(resp.text)
    if not index:
        raise RuntimeError("No se encontraron enlaces mensuales: la CMF cambió el formato de la página.")
    return index


def download_all(raw_dir: Path, delay: float = 0.4, retries: int = 3) -> list[Path]:
    """Descarga los meses que faltan. Idempotente: no vuelve a bajar archivos válidos."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    index = fetch_index(session)
    paths: list[Path] = []
    for month, filename in sorted(index.items()):
        target = raw_dir / f"{month:%Y-%m}.xlsx"
        if not _is_xlsx(target):
            for attempt in range(1, retries + 1):
                resp = session.get(BASE_URL + filename, headers={"User-Agent": USER_AGENT}, timeout=60)
                if resp.status_code == 200 and resp.content[:2] == b"PK":
                    target.write_bytes(resp.content)
                    break
                time.sleep(delay * attempt * 2)
            else:
                raise RuntimeError(f"No se pudo descargar {month:%Y-%m} ({filename})")
            time.sleep(delay)
        paths.append(target)
    return paths


if __name__ == "__main__":
    files = download_all(Path("data/raw"))
    print(f"{len(files)} archivos mensuales en data/raw ({files[0].stem} -> {files[-1].stem})")
