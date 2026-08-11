from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_JOURNAL = Path("/root/nw-agent/runtime/openclaw-message-journal.jsonl")


@dataclass(slots=True)
class JournalRecord:
    type: str
    received_at: datetime
    peer: str
    content: str
    raw: dict[str, Any]

    @property
    def is_command(self) -> bool:
        return self.content.strip().startswith("/")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def load_records(path: Path, since: datetime) -> list[JournalRecord]:
    if not path.exists():
        return []

    records: list[JournalRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip().lstrip("\ufeff")
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            received_at = parse_timestamp(payload.get("received_at"))
            if received_at is None or received_at < since:
                continue

            peer = payload.get("peer")
            if not isinstance(peer, str) or not peer:
                continue

            records.append(
                JournalRecord(
                    type=str(payload.get("type") or ""),
                    received_at=received_at,
                    peer=peer,
                    content=str(payload.get("content") or ""),
                    raw=payload,
                )
            )
    return records


def pending_by_peer(records: list[JournalRecord], include_commands: bool = False) -> list[JournalRecord]:
    last_sent: dict[str, datetime] = {}
    inbound: list[JournalRecord] = []

    for record in sorted(records, key=lambda item: item.received_at):
        if record.type == "sent":
            last_sent[record.peer] = record.received_at
        elif record.type == "received" and (include_commands or not record.is_command):
            inbound.append(record)

    never_replied = datetime.min.replace(tzinfo=UTC)
    return [r for r in inbound if last_sent.get(r.peer, never_replied) < r.received_at]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report WhatsApp inbound messages captured by OpenClaw with no later outbound reply."
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--minutes", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-pending", action="store_true")
    parser.add_argument("--include-commands", action="store_true", help="Include slash commands like /new.")
    parser.add_argument("--show-events", action="store_true", help="Include raw matching events in JSON output.")
    args = parser.parse_args()

    now = datetime.now(UTC)
    since = now - timedelta(minutes=args.minutes)
    records = load_records(args.journal, since)
    pending = pending_by_peer(records, include_commands=args.include_commands)

    if args.json:
        print(
            json.dumps(
                {
                    "journal": str(args.journal),
                    "window_minutes": args.minutes,
                    "event_count": len(records),
                    "pending_count": len(pending),
                    "pending": [
                        {
                            "received_at": item.received_at.isoformat(),
                            "peer": item.peer,
                            "content": item.content,
                            "session_key": item.raw.get("session_key"),
                            "metadata": item.raw.get("metadata"),
                        }
                        for item in pending
                    ],
                    **(
                        {
                            "events": [
                                {
                                    "type": item.type,
                                    "received_at": item.received_at.isoformat(),
                                    "peer": item.peer,
                                    "content": item.content,
                                    "session_key": item.raw.get("session_key"),
                                    "metadata": item.raw.get("metadata"),
                                }
                                for item in records
                            ]
                        }
                        if args.show_events
                        else {}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif pending:
        print(f"Pending WhatsApp messages in last {args.minutes} minutes:")
        for item in pending:
            print(f"- {item.received_at.isoformat()} {item.peer}: {item.content}")
    else:
        print(f"No pending WhatsApp messages in last {args.minutes} minutes.")

    return 2 if pending and args.fail_on_pending else 0


if __name__ == "__main__":
    sys.exit(main())
