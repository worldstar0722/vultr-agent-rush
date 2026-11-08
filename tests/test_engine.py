"""Engine unit tests on hand-built evidence (states that no fixture case covers)."""

from app.engine import analyze

POL = {
    "version": "POL-LATE-v1",
    "params": {
        "late_percent": 20,
        "max_late_hours": 24,
        "grade_basis": "latest_attempt",
        "exception_authority": "professor",
    },
}


def ev(kind, ref, ts, **payload):
    return {
        "ref_id": ref,
        "source_type": kind,
        "ts": ts,
        "summary": "",
        "source_text": "",
        "payload": payload,
    }


def base(attempts, applied=0, entered=10):
    rows = [
        ev(
            "deadline",
            "DL-X",
            "2026-11-05T23:59:00-07:00",
            deadline="2026-11-05T23:59:00-07:00",
            max_points=10,
            policy_ref="POL-LATE-v1",
        ),
        ev("policy", "POL-LATE-v1", "2026-08-24T00:00:00-07:00", **POL),
        ev("rubric", "RUB-X-row1", "2026-11-07T09:00:00-07:00", label="all", max=10, awarded=10),
        ev(
            "score",
            "SCORE-X",
            "2026-11-07T09:00:00-07:00",
            entered=entered,
            posted=entered,
            graded=True,
            late_deduction_applied=applied,
        ),
    ]
    return rows + attempts


def att(ref, ts, state="submitted"):
    return ev("attempt", ref, ts, state=state)


def test_not_submitted_unreadable_empty_and_alternate_are_distinct_states():
    ok = att("ATT-X1", "2026-11-05T20:00:00-07:00")
    states = {}
    for state in ("unreadable", "empty_file", "alternate_evidence"):
        a = analyze(base([att("ATT-X1", "2026-11-05T20:00:00-07:00", state)]))
        states[state] = a
        assert a["submission_state"] == state
    assert analyze(base([]))["submission_state"] == "not_submitted"
    assert analyze(base([ok]))["submission_state"] == "submitted"
    assert any(
        "unreadable" in w["text"] and w["text"].startswith("Insufficient evidence")
        for w in states["unreadable"]["warnings"]
    )
    assert any("empty file" in w["text"] for w in states["empty_file"]["warnings"])
    alt = states["alternate_evidence"]
    assert alt["requires_professor"] and not alt["blockers"]  # professor decides, not a hard hold
    assert states["unreadable"]["suggested_action"] == "request_info"


def test_recorded_deduction_that_contradicts_attempt_time_is_a_records_conflict():
    a = analyze(base([att("ATT-X1", "2026-11-05T20:00:00-07:00")], applied=2, entered=8))
    assert any(b["code"] == "records_conflict" for b in a["blockers"])
    assert a["suggested_action"] == "hold"


def test_late_beyond_window_and_exact_deduction():
    a = analyze(base([att("ATT-X1", "2026-11-06T10:00:00-07:00")], applied=2, entered=8))
    assert a["score_state"]["expected_deduction"] == 2 and a["score_state"]["expected_final"] == 8
    assert a["blockers"] == []
    far = analyze(base([att("ATT-X1", "2026-11-08T10:00:00-07:00")], applied=2, entered=8))
    assert far["score_state"]["basis"]["lateness"] == "beyond_window"


def test_graded_but_not_posted_is_reported():
    rows = base([att("ATT-X1", "2026-11-05T20:00:00-07:00")])
    next(r for r in rows if r["source_type"] == "score")["payload"]["posted"] = None
    codes = [d["code"] for d in analyze(rows)["score_state"]["differences"]]
    assert "graded_not_posted" in codes
