from __future__ import annotations

from src.features.pipeline import BaselineFeaturePipeline
from tests.feature_snapshot_support import make_bundle


def _run(bundle, code_sha: str):
    return BaselineFeaturePipeline(
        bundle.config,
        snapshot_store=bundle.store,
        code_commit_sha=code_sha,
    ).run(
        yfinance_raw_snapshot_ids=bundle.yfinance_ids,
        isyatirim_raw_snapshot_ids=bundle.isyatirim_ids,
        identity_snapshot_id=bundle.identity_id,
        xu100_snapshot_id=bundle.xu100_id,
        calendar_snapshot_id=bundle.calendar_id,
    )


def test_same_feature_content_and_context_is_idempotent(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    first = _run(bundle, "a" * 40)
    second = _run(bundle, "a" * 40)

    assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert second.snapshot.revision_number == 1


def test_code_provenance_change_creates_new_feature_revision(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    first = _run(bundle, "a" * 40)
    second = _run(bundle, "b" * 40)

    assert second.snapshot.content_checksum == first.snapshot.content_checksum
    assert second.snapshot.logical_dataset_key == first.snapshot.logical_dataset_key
    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert second.snapshot.revision_number == 2
    assert second.snapshot.previous_snapshot_id == first.snapshot.snapshot_id


def test_irrelevant_raw_provider_revision_still_revises_feature_lineage(tmp_path) -> None:
    first_bundle = make_bundle(tmp_path, action_value=0.0)
    first = _run(first_bundle, "a" * 40)
    second_bundle = make_bundle(
        tmp_path,
        store=first_bundle.store,
        action_value=1.0,
    )
    second = _run(second_bundle, "a" * 40)

    assert second.frame.equals(first.frame)
    assert second.snapshot.content_checksum == first.snapshot.content_checksum
    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert second.snapshot.revision_number == 2
    assert second.snapshot.revision_context_checksum != first.snapshot.revision_context_checksum
