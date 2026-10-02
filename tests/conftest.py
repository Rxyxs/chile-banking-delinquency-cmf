import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def panel() -> pd.DataFrame:
    """Panel real (datos de la CMF) versionado en el repo."""
    return pd.read_csv(ROOT / "data" / "panel_mora90.csv", parse_dates=["date"])
