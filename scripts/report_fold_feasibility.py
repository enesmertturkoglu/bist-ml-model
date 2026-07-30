"""Generate D031 fold-feasibility reports from an auditable training panel CSV."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modeling.fold_feasibility import write_fold_feasibility_reports  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-panel-csv", type=Path, required=True)
    parser.add_argument("--global-calendar-csv", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument(
        "--report-root", type=Path, default=Path("reports/full_history")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    panel = pd.read_csv(args.training_panel_csv)
    calendar = pd.read_csv(args.global_calendar_csv)
    paths = write_fold_feasibility_reports(
        panel,
        calendar,
        report_root=args.report_root,
        as_of_date=args.as_of_date,
    )
    for name, path in paths.items():
        print(f"{name}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
