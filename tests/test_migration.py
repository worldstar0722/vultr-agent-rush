import sqlite3

from app.config import Settings
from app.db import init_db
from tests.conftest import make_client


def old_database(path):
    """A database as the previously deployed version created it."""
    init_db(path)
    with sqlite3.connect(path) as c:
        c.execute("ALTER TABLE response_drafts DROP COLUMN run_id")
        for t in ("analysis_runs", "ai_usage_total", "ai_attempt_log", "ai_client_calls"):
            c.execute(f"DROP TABLE {t}")


def test_old_database_is_upgraded_in_place_and_keeps_its_data(tmp_path):
    path = str(tmp_path / "old.db")
    old_database(path)
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO cases (id, course, assignment, student_id, created_at, updated_at) "
                  "VALUES ('CASE-OLD','DEMO 3060','HW1','S-0001','t','t')")  # fmt: skip
    client = make_client(Settings(db_path=path))
    ids = {c["id"] for c in client.get("/api/cases").json()}
    assert "CASE-OLD" in ids  # existing rows untouched (and fixtures not re-seeded over them)
    with sqlite3.connect(path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(response_drafts)")}
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert (
        "run_id" in cols
        and {"analysis_runs", "ai_usage_total", "ai_attempt_log", "ai_client_calls"} <= tables
    )
    assert client.get("/api/ai/status").status_code == 200


def test_init_is_idempotent(tmp_path):
    path = str(tmp_path / "x.db")
    for _ in range(3):
        init_db(path)
