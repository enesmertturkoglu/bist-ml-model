"""Prediction-date-only cross-sectional baseline ranks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from src.features.input_assembler import validate_feature_input_schema


CROSS_SECTIONAL_SOURCES: Mapping[str, str] = {
    "cs_ret_1_rank": "ret_1",
    "cs_ret_5_rank": "ret_5",
    "cs_relative_ret_5_rank": "relative_ret_5",
    "cs_volume_anomaly_rank": "tl_volume_zscore_20",
}


@dataclass(frozen=True)
class CrossSectionalComputation:
    frame: pd.DataFrame
    insufficient_masks: Mapping[str, pd.Series]


def add_cross_sectional_features(
    frame: pd.DataFrame, *, minimum_securities: int = 20
) -> CrossSectionalComputation:
    """Apply average ties and (rank-1)/(N-1) within prediction_date only."""

    if minimum_securities < 2:
        raise ValueError("minimum_securities must be at least two")
    validate_feature_input_schema(frame)
    required = {"security_id", "prediction_date", *CROSS_SECTIONAL_SOURCES.values()}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"cross-sectional fields missing: {sorted(missing)}")
    result = frame.copy()
    masks: dict[str, pd.Series] = {}
    for target, source in CROSS_SECTIONAL_SOURCES.items():
        counts = result.groupby("prediction_date", sort=False)[source].transform("count")
        raw_rank = result.groupby("prediction_date", sort=False)[source].rank(
            method="average", na_option="keep"
        )
        value = (raw_rank - 1.0) / (counts - 1.0)
        sufficient = counts.ge(minimum_securities)
        result[target] = value.where(sufficient)
        masks[target] = result[source].notna() & ~sufficient
    return CrossSectionalComputation(result, masks)
