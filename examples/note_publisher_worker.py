from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.publisher_client import PublisherClient
from app.integrations.publisher_worker import PublishOutcome, PublisherAdapter, PublisherWorker


@dataclass(slots=True)
class NotePublisherAdapter(PublisherAdapter):
    """Sample adapter showing where the real note publish logic should plug in."""

    @property
    def platform(self) -> str:
        return "note"

    def publish(self, artifact: dict[str, object]) -> PublishOutcome:
        title = artifact.get("title")
        content = artifact.get("content")
        if not isinstance(content, str) or not content.strip():
            return PublishOutcome(
                published=False,
                status="failed",
                error_message="Artifact content is empty.",
            )
        safe_title = title or "Untitled note artifact"
        slug = safe_title.lower().replace(" ", "-")[:48]
        published_url = f"https://note.example.com/{slug}"
        external_publish_id = f"note_{abs(hash((safe_title, len(content))))}"
        return PublishOutcome(
            published=True,
            published_url=published_url,
            external_publish_id=external_publish_id,
            status="published",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample note publisher worker for Content Orchestrator.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Content Orchestrator base URL")
    parser.add_argument("--consumer-name", default="note-auto-publisher", help="Publisher consumer name")
    parser.add_argument("--limit", type=int, default=1, help="How many artifacts to claim")
    parser.add_argument("--api-key", default=None, help="Publisher API bearer token")
    args = parser.parse_args()

    client = PublisherClient(base_url=args.base_url, api_key=args.api_key)
    worker = PublisherWorker(
        client=client,
        adapter=NotePublisherAdapter(),
        consumer_name=args.consumer_name,
    )
    results = worker.run_once(limit=args.limit)

    if not results:
        print("No note artifacts available.")
        return

    for result in results:
        if result["published"]:
            print(f"Published {result['id']} -> {result['published_url']}")
        else:
            print(f"Failed {result['id']}: {result.get('review_notes') or 'unknown error'}")


if __name__ == "__main__":
    main()
