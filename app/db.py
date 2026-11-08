"""SQLite persistence. Plain sqlite3, one short-lived connection per operation.

Source text (what people wrote, what systems recorded) lives in `evidence`.
AI-generated text lives only in `response_drafts` and `recommendations`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  course TEXT NOT NULL,
  assignment TEXT NOT NULL,
  assignment_name TEXT NOT NULL DEFAULT '',
  student_id TEXT NOT NULL,            -- pseudonymous id, never a real name
  owner TEXT,
  status TEXT NOT NULL DEFAULT 'New',
  issue TEXT NOT NULL DEFAULT 'other',
  status_note TEXT NOT NULL DEFAULT '',
  on_hold INTEGER NOT NULL DEFAULT 0,
  merged_into TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id),
  source_type TEXT NOT NULL,           -- message|attempt|deadline|rubric|score|policy|approval|submission_status
  ref_id TEXT NOT NULL,                -- stable source id, e.g. ATT-A1
  ts TEXT NOT NULL,
  summary TEXT NOT NULL,               -- written by code
  source_text TEXT NOT NULL DEFAULT '',-- verbatim source (student message, policy text)
  payload TEXT NOT NULL DEFAULT '{}',
  UNIQUE(case_id, ref_id)
);
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id),
  source TEXT NOT NULL,                -- rules|ai|score_change
  rationale TEXT NOT NULL,
  uncertainty TEXT NOT NULL DEFAULT '',
  evidence_ids TEXT NOT NULL DEFAULT '[]',
  policy_version TEXT,
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id),
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT NOT NULL,
  ts TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  from_status TEXT,
  to_status TEXT
);
CREATE TABLE IF NOT EXISTS response_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id),
  version INTEGER NOT NULL,
  body_ai TEXT NOT NULL,               -- AI (or rules-only template) output, never edited
  body_edited TEXT,                    -- human edits
  body_final TEXT,                     -- text approved by a human (still never sent)
  verified TEXT NOT NULL DEFAULT '[]',
  unverified TEXT NOT NULL DEFAULT '[]',
  flags TEXT NOT NULL DEFAULT '[]',
  ai_status TEXT NOT NULL,             -- mock|ok|unavailable
  source TEXT NOT NULL,                -- mock|llm|rules-only
  classification_ai TEXT NOT NULL DEFAULT '',
  summary_ai TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT
);
CREATE TABLE IF NOT EXISTS review_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  route_to TEXT NOT NULL,              -- professor|student|ta
  status TEXT NOT NULL DEFAULT 'open',
  evidence_ids TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(case_id, kind)
);
CREATE TABLE IF NOT EXISTS duplicates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_a TEXT NOT NULL,
  case_b TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',  -- proposed|confirmed|dismissed
  created_at TEXT NOT NULL,
  UNIQUE(case_a, case_b)
);
"""

TABLES = (
    "duplicates",
    "review_items",
    "response_drafts",
    "decisions",
    "recommendations",
    "evidence",
    "cases",
)


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


def clear_all(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
    conn.execute("DELETE FROM sqlite_sequence")


def j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def row_dict(row: sqlite3.Row, json_cols: tuple[str, ...] = ()) -> dict[str, Any]:
    d = dict(row)
    for col in json_cols:
        if col in d and isinstance(d[col], str):
            d[col] = json.loads(d[col])
    return d
