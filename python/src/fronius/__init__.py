"""Client package for Fronius."""

from .client import FroniusClient
from solar_data_normalization import (
    NORMALIZED_DAILY_INVERTER_FIELDS,
    normalize_daily_inverter_row,
    normalize_solar_data,
)

__all__ = [
    "FroniusClient",
    "NORMALIZED_DAILY_INVERTER_FIELDS",
    "normalize_daily_inverter_row",
    "normalize_solar_data",
]
