"""Local retry queue for failed Notion saves."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Any

from notion_client import NotionRecord

QUEUE_PATH = Path(__file__).resolve().parent / "retry_queue.jsonl"


def enqueue(record: NotionRecord, error: str) -> None:
    payload = asdict(record)
    payload["last_error"] = error
    try:
        with QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logging.exception("Failed to write retry queue: %s", exc)


def load_queue() -> List[Dict[str, Any]]:
    if not QUEUE_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with QUEUE_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                logging.warning("Bad queue line skipped")
    return rows


def rewrite_queue(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        try:
            QUEUE_PATH.unlink(missing_ok=True)
        except TypeError:
            if QUEUE_PATH.exists():
                QUEUE_PATH.unlink()
        return
    with QUEUE_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
