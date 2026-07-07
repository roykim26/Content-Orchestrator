from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlmodel import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import engine
from app.services.topic_import_service import TopicImportService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk import manual topics from CSV, JSON, or Excel.")
    parser.add_argument("input_path", help="Path to a CSV, JSON, or Excel file.")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Plan each created topic immediately after import.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview rows without writing to the database.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip rows when master_topic + target_keyword already exist.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path).resolve()

    with Session(engine) as session:
        service = TopicImportService(session)
        summary = service.import_from_path(
            input_path,
            plan=args.plan,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
        )

    for result in summary["results"]:
        status = result["status"]
        row = result["row"]
        if status == "preview":
            print(
                f"[DRY-RUN] row={row} master_topic={result['master_topic']!r} "
                f"platforms={result['target_platforms']}"
            )
        elif status == "skipped":
            print(
                f"[SKIP] row={row} master_topic={result['master_topic']!r} "
                f"target_keyword={result['target_keyword']!r}"
            )
        elif status == "created":
            print(
                f"[CREATED] row={row} topic_id={result['topic_id']} "
                f"master_topic={result['master_topic']!r}"
            )
        elif status == "planned":
            print(
                f"[CREATED] row={row} topic_id={result['topic_id']} "
                f"master_topic={result['master_topic']!r}"
            )
            print(
                f"[PLANNED] row={row} topic_id={result['topic_id']} "
                f"task_count={result.get('task_count', 0)}"
            )
        else:
            print(f"[ERROR] row={row} reason={result['reason']}")

    summary.pop("results", None)

    print()
    print("Import summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
