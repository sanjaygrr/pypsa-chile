from pathlib import Path

import pandas as pd
import pytest

from pypsa_chile.config import load_config
from pypsa_chile.parse import read_capacity_by_region

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg():
    """Default config shortened to one day with a two-day look-back."""
    c = load_config()
    c["period"] = {"start": "2025-10-06", "end": "2025-10-06"}
    c["thermal_availability"]["window_days"] = 2
    return c


@pytest.fixture(scope="session")
def capacity():
    return read_capacity_by_region(FIXTURES / "capacity_by_region.xlsx")


@pytest.fixture(scope="session")
def generation():
    return pd.read_csv(FIXTURES / "generation_processed_excerpt.csv.gz", parse_dates=["time"])
