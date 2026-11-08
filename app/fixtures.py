"""Synthetic demo data. Every name, id and message here is invented.

Course "DEMO 3060". Times are in UTC-07:00. Nothing here comes from a real LMS.
"""

from __future__ import annotations

from typing import Any

COURSE = "DEMO 3060"

POLICIES: dict[str, dict[str, Any]] = {
    "POL-LATE-v1": {
        "effective": "2026-08-24T00:00:00-07:00",
        "text": (
            "DEMO 3060 Late Work Policy (v1, synthetic). "
            "1. Work submitted after the deadline and within 24 hours loses 20% of the "
            "assignment's maximum points. "
            "2. Work submitted more than 24 hours after the deadline is not accepted. "
            "3. When a student has several attempts, the most recent attempt is graded and "
            "its submission time determines lateness, unless the instructor approves "
            "otherwise. "
            "4. Exceptions to this policy can be approved only by the instructor."
        ),
        "params": {
            "late_percent": 20,
            "max_late_hours": 24,
            "grade_basis": "latest_attempt",
            "exception_authority": "professor",
        },
    }
}

# One entry per (student, assignment). `letter` is used in the stable source ids.
CONTEXTS: list[dict[str, Any]] = [
    {
        "letter": "A",
        "student": "S-7F3A",
        "assignment": "HW3",
        "name": "Homework 3",
        "deadline": "2026-11-05T23:59:00-07:00",
        "max_points": 10,
        "policy_ref": "POL-LATE-v1",
        "attempts": [
            {"ts": "2026-11-05T22:40:00-07:00", "state": "submitted", "file": "hw3_v1.pdf"},
            {"ts": "2026-11-06T00:10:00-07:00", "state": "submitted", "file": "hw3_v2.pdf"},
        ],
        "rubric": [
            {"label": "Problem 1", "max": 3, "awarded": 3},
            {"label": "Problem 2", "max": 3, "awarded": 3},
            {"label": "Problem 3", "max": 2, "awarded": 2},
            {"label": "Problem 4", "max": 2, "awarded": 1},
        ],
        "score": {
            "entered": 7,
            "posted": 7,
            "graded": True,
            "late_deduction_applied": 2,
            "graded_attempt": "ATT-A2",
            "graded_at": "2026-11-07T09:00:00-07:00",
        },
    },
    {
        "letter": "B",
        "student": "S-2C91",
        "assignment": "HW4",
        "name": "Homework 4",
        "deadline": "2026-11-03T23:59:00-07:00",
        "max_points": 10,
        "policy_ref": "POL-LATE-v1",
        "attempts": [
            {"ts": "2026-11-03T21:15:00-07:00", "state": "submitted", "file": "hw4.pdf"},
        ],
        "rubric": [{"label": f"Row {i}", "max": 2, "awarded": 2} for i in range(1, 6)],
        "score": {
            "entered": 8,
            "posted": 8,
            "graded": True,
            "late_deduction_applied": 0,
            "graded_attempt": "ATT-B1",
            "graded_at": "2026-11-06T16:00:00-07:00",
        },
    },
    {
        "letter": "C",
        "student": "S-5D08",
        "assignment": "HW5",
        "name": "Homework 5",
        "deadline": "2026-11-06T23:59:00-07:00",
        "max_points": 10,
        "policy_ref": "POL-LATE-v2",  # deliberately missing from POLICIES -> "hold" path
        "attempts": [],
        "submission_status": {"state": "not_submitted", "checked_at": "2026-11-07T18:00:00-07:00"},
        "rubric": [],
        "score": {
            "entered": None,
            "posted": None,
            "graded": False,
            "late_deduction_applied": 0,
            "graded_attempt": None,
            "graded_at": "2026-11-07T18:00:00-07:00",
        },
    },
    {
        "letter": "D",
        "student": "S-7F3A",
        "assignment": "HW2",
        "name": "Homework 2",
        "deadline": "2026-10-29T23:59:00-07:00",
        "max_points": 10,
        "policy_ref": "POL-LATE-v1",
        "attempts": [
            {"ts": "2026-10-29T23:30:00-07:00", "state": "submitted", "file": "hw2.pdf"},
        ],
        "rubric": [
            {"label": "Part 1", "max": 5, "awarded": 5},
            {"label": "Part 2", "max": 5, "awarded": 4},
        ],
        "score": {
            "entered": 9,
            "posted": 9,
            "graded": True,
            "late_deduction_applied": 0,
            "graded_attempt": "ATT-D1",
            "graded_at": "2026-11-02T10:00:00-07:00",
        },
    },
]

# Synthetic inbound/outbound messages. `case_id` groups messages into the same thread.
MESSAGES: list[dict[str, Any]] = [
    {
        "id": "MSG-A1",
        "case_id": "CASE-A",
        "channel": "canvas_inbox",
        "direction": "inbound",
        "author": "S-7F3A",
        "role": "student",
        "student": "S-7F3A",
        "assignment": "HW3",
        "ts": "2026-11-06T08:05:00-07:00",
        "owner": "TA Rivera",
        "text": (
            "I submitted on time but it shows late on my HW3. I uploaded the file at "
            "10:40 pm on Nov 5, before the deadline. Please fix the late mark."
        ),
    },
    {
        "id": "MSG-A2",
        "case_id": "CASE-A2",
        "channel": "email",
        "direction": "inbound",
        "author": "S-7F3A",
        "role": "student",
        "student": "S-7F3A",
        "assignment": "HW3",
        "ts": "2026-11-06T08:20:00-07:00",
        "owner": "TA Chen",
        "text": "Following up by email: I submitted on time but it says late for HW3. Can someone check?",
    },
    {
        "id": "MSG-A3",
        "case_id": "CASE-A",
        "channel": "submission_comment",
        "direction": "outbound",
        "author": "TA Rivera",
        "role": "ta",
        "student": "S-7F3A",
        "assignment": "HW3",
        "ts": "2026-11-07T10:00:00-07:00",
        "text": "Thanks, we are checking the submission history and will follow up.",
    },
    {
        "id": "MSG-B1",
        "case_id": "CASE-B",
        "channel": "canvas_inbox",
        "direction": "inbound",
        "author": "S-2C91",
        "role": "student",
        "student": "S-2C91",
        "assignment": "HW4",
        "ts": "2026-11-07T14:10:00-07:00",
        "owner": "TA Chen",
        "text": "My HW4 rubric shows full marks on every row but my score is 8 out of 10. Can you check?",
    },
    {
        "id": "MSG-C1",
        "case_id": "CASE-C",
        "channel": "email",
        "direction": "inbound",
        "author": "S-5D08",
        "role": "student",
        "student": "S-5D08",
        "assignment": "HW5",
        "ts": "2026-11-07T18:30:00-07:00",
        "owner": None,
        "text": (
            "I emailed my HW5 file to the TA before the deadline, but Canvas shows nothing "
            "submitted. Please grade it."
        ),
    },
    {
        "id": "MSG-D1",
        "case_id": "CASE-D",
        "channel": "canvas_inbox",
        "direction": "inbound",
        "author": "S-7F3A",
        "role": "student",
        "student": "S-7F3A",
        "assignment": "HW2",
        "ts": "2026-11-06T08:30:00-07:00",
        "owner": "TA Rivera",
        "text": "I submitted on time but it shows late on HW2 too.",
    },
]
