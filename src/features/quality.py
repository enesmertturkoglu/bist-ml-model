"""Compact per-feature quality accounting for baseline_v1 snapshots."""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from src.features.catalog import BASELINE_V1_FEATURES


QUALITY_COUNT_COLUMNS: tuple[str, ...] = (
    "valid",
    "missing",
    "warmup",
    "source_missing",
    "invalid_math",
    "xu100_missing",
    "cross_section_insufficient",
    "infinite_replaced",
)


def build_quality_summary(
    frame: pd.DataFrame,
    reason_masks: Mapping[str, Mapping[str, pd.Series]],
) -> pd.DataFrame:
    """Return one compact row per feature, not per-row reason columns."""

    rows: list[dict[str, object]] = []
    for feature in BASELINE_V1_FEATURES:
        values = frame[feature]
        feature_masks = reason_masks.get(feature, {})
        row: dict[str, object] = {
            "feature_name": feature,
            "valid": int(values.notna().sum()),
            "missing": int(values.isna().sum()),
        }
        for reason in QUALITY_COUNT_COLUMNS[2:]:
            mask = feature_masks.get(reason)
            row[reason] = int(mask.sum()) if mask is not None else 0
        rows.append(row)
    return pd.DataFrame(rows, columns=["feature_name", *QUALITY_COUNT_COLUMNS])
