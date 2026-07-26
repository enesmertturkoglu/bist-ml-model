"""Data-access clients used by the project."""

from .isyatirim_client import (
    ClientStats,
    IsYatirimClient,
    IsYatirimFetchError,
    IsYatirimSchemaError,
    fetch_isyatirim_history,
)

__all__ = [
    "ClientStats",
    "IsYatirimClient",
    "IsYatirimFetchError",
    "IsYatirimSchemaError",
    "fetch_isyatirim_history",
]
