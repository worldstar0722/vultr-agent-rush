from tests.conftest import detail


def test_canvas_and_email_same_assignment_is_one_candidate(client):
    cases = {c["id"]: c for c in client.get("/api/cases").json()}
    assert [d["other"] for d in cases["CASE-A"]["duplicates"]] == ["CASE-A2"]
    assert [d["other"] for d in cases["CASE-A2"]["duplicates"]] == ["CASE-A"]
    assert cases["CASE-A"]["duplicates"][0]["id"] == cases["CASE-A2"]["duplicates"][0]["id"]
    # nothing was merged automatically
    assert all(c["merged_into"] is None for c in cases.values())


def test_same_student_different_assignment_is_not_proposed(client):
    cases = {c["id"]: c for c in client.get("/api/cases").json()}
    assert cases["CASE-A"]["student_id"] == cases["CASE-D"]["student_id"]
    assert cases["CASE-A"]["assignment"] != cases["CASE-D"]["assignment"]
    assert cases["CASE-D"]["duplicates"] == []
    assert all(d["other"] != "CASE-D" for c in cases.values() for d in c["duplicates"])


def test_confirm_merge_combines_evidence_and_is_logged(client):
    dup_id = client.get("/api/cases").json()[0]["duplicates"][0]["id"]
    assert client.post(f"/api/duplicates/{dup_id}/confirm", json={"role": "ta"}).status_code == 200
    ids = [c["id"] for c in client.get("/api/cases").json()]
    assert "CASE-A2" not in ids and "CASE-A" in ids
    refs = [e["ref_id"] for e in detail(client, "CASE-A")["evidence"]]
    assert "MSG-A2" in refs and refs.count("ATT-A1") == 1
    assert any(x["action"] == "merge" for x in detail(client, "CASE-A")["decisions"])
    assert client.post(f"/api/duplicates/{dup_id}/confirm", json={"role": "ta"}).status_code == 409


def test_dismiss_removes_badge(client):
    dup_id = client.get("/api/cases").json()[0]["duplicates"][0]["id"]
    client.post(f"/api/duplicates/{dup_id}/dismiss", json={"role": "ta"})
    assert all(c["duplicates"] == [] for c in client.get("/api/cases").json())
