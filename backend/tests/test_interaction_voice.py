import app.routers.interactions as interactions_router
import app.db as db
from conftest import insert_profile


def _profile(iso):
    insert_profile("Rohan Verma", status="Talking", ai_fit_score=61)
    conn = db.get_conn()
    pid = conn.execute("SELECT id FROM profiles").fetchone()[0]
    conn.close()
    return pid


def _post_voice(iso, pid, text=""):
    return iso.post(
        f"/api/profiles/{pid}/interactions",
        headers=iso.member_headers,
        data={"title": "Call", "raw_text": text},
        files={"audio_file": ("note.m4a", b"fake-audio-bytes", "audio/mp4")},
    )


def _profile_row(pid):
    conn = db.get_conn()
    row = dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (pid,)).fetchone())
    conn.close()
    return row


def _count(table):
    conn = db.get_conn()
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


BUNDLE = {
    "extracted_fields": {"annual_ctc": "35 LPA", "current_city": "Gurgaon", "diet": "Vegetarian"},
    "voice_transcript": "Ladke ka package 35 LPA hai",
    "interaction_summary": "Package 35 LPA, Gurgaon, vegetarian.",
    "suggested_status": "Shortlisted",
    "ai_fit_score": 82,
    "suggested_follow_up": {"task": "Ask for kundli", "due_days": 2},
}


def test_offline_voice_note_is_queued_not_faked(iso):
    pid = _profile(iso)
    r = _post_voice(iso, pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_pending"] is True and body["task_id"]
    assert body["summary"] == "Voice note — transcription pending (Mac AI)"

    p = _profile_row(pid)
    assert p["status"] == "Talking" and p["ai_fit_score"] == 61
    assert _count("follow_ups") == 0

    conn = db.get_conn()
    task = dict(conn.execute("SELECT * FROM worker_tasks WHERE id = ?", (body["task_id"],)).fetchone())
    asset = dict(conn.execute("SELECT * FROM media_assets WHERE asset_type='voice_note'").fetchone())
    conn.close()
    assert task["task_type"] == "update_profile_from_interaction" and task["target_id"] == body["interaction_id"]
    import json

    payload = json.loads(task["payload_json"])
    assert payload["media_asset_ids"] == [asset["id"]] and payload["target_profile_id"] == pid
    assert asset["mime_type"] == "audio/mp4"


def test_worker_completion_applies_once(iso):
    pid = _profile(iso)
    body = _post_voice(iso, pid).json()
    tid, iid = body["task_id"], body["interaction_id"]

    r = iso.post(f"/api/worker/tasks/{tid}/complete", headers=iso.worker_headers, json={"ai_bundle": BUNDLE})
    assert r.status_code == 200
    p = _profile_row(pid)
    assert p["annual_ctc"] == "35 LPA" and p["current_city"] == "Gurgaon" and p["diet"] == "Vegetarian"
    assert p["status"] == "Shortlisted" and p["ai_fit_score"] == 82
    conn = db.get_conn()
    i = dict(conn.execute("SELECT * FROM interactions WHERE id = ?", (iid,)).fetchone())
    conn.close()
    assert i["transcript"] == BUNDLE["voice_transcript"] and i["summary"] == BUNDLE["interaction_summary"]
    assert i["ai_applied_at"]
    assert _count("follow_ups") == 1

    second = {**BUNDLE, "extracted_fields": {"current_city": "Pune"}}
    iso.post(f"/api/worker/tasks/{tid}/complete", headers=iso.worker_headers, json={"ai_bundle": second})
    assert _profile_row(pid)["current_city"] == "Gurgaon"
    assert _count("follow_ups") == 1


def test_offline_fallback_result_is_not_applied(iso):
    pid = _profile(iso)
    body = _post_voice(iso, pid).json()
    iso.post(
        f"/api/worker/tasks/{body['task_id']}/complete",
        headers=iso.worker_headers,
        json={"ai_bundle": {**BUNDLE, "pending_mac_ai": True}},
    )
    assert _profile_row(pid)["current_city"] is None
    assert _count("follow_ups") == 0


def test_local_extract_applies_directly(iso, monkeypatch):
    pid = _profile(iso)
    monkeypatch.setattr(interactions_router, "ZLLAMA_API_KEY", "key")
    monkeypatch.setattr(interactions_router, "_local_extract", lambda raw, path, existing: dict(BUNDLE))
    r = iso.post(
        f"/api/profiles/{pid}/interactions",
        headers=iso.member_headers,
        data={"title": "Call", "raw_text": "package 35 LPA"},
    )
    body = r.json()
    assert body["ai_pending"] is False and body["task_id"] is None
    assert body["transcript"] == BUNDLE["voice_transcript"]
    p = _profile_row(pid)
    assert p["current_city"] == "Gurgaon" and p["status"] == "Shortlisted"
    assert _count("follow_ups") == 1
    assert _count("worker_tasks") == 0
