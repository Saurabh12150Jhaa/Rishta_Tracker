import io
import subprocess
import pymupdf as fitz
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db


def _make_sample_biodata_pdf(name: str = "Rohan Verma", company: str = "Google India", city: str = "Bangalore") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = (
        f"BIODATA\n\n"
        f"Name: {name}\n"
        f"Gender: Male\n"
        f"Date of Birth: 14 Aug 1996 (Age: 29)\n"
        f"Time of Birth: 06:15 AM\n"
        f"Place of Birth: Lucknow, UP\n"
        f"Height: 5'10\"\n"
        f"Gotra: Kashyap\n"
        f"Manglik: No\n"
        f"Diet: Vegetarian\n"
        f"Education: B.Tech (IIT Delhi), MBA\n"
        f"Occupation: Staff Software Engineer at {company}\n"
        f"Annual Package: 48 LPA\n"
        f"Current Location: {city}\n"
        f"Father: Mr. Rajesh Verma (Retd. Chief Engineer)\n"
        f"Mother: Mrs. Meena Verma (Homemaker)\n"
        f"Contact (Father): +91 9811122334\n"
    )
    page.insert_text((50, 60), text, fontsize=12)

    portrait = Image.new("RGB", (320, 400), color=(90, 120, 160))
    img_buf = io.BytesIO()
    portrait.save(img_buf, format="JPEG", quality=90)
    page.insert_image(fitz.Rect(380, 60, 540, 260), stream=img_buf.getvalue())

    out = doc.tobytes()
    doc.close()
    return out


def _make_sample_opus_bytes() -> bytes:
    ffmpeg = "/opt/homebrew/bin/ffmpeg"
    res = subprocess.run(
        [
            ffmpeg,
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-f",
            "ogg",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return res.stdout


def test_full_rishta_workflow():
    init_db()
    client = TestClient(app)

    # 1. Verify 'Papa' is removed from login members and 'Saurabh', 'Mummy', 'Sister' exist
    members_res = client.get("/api/auth/members").json()["members"]
    member_names = [m["name"].lower() for m in members_res]
    assert "papa" not in member_names and "father" not in member_names
    assert "saurabh" in member_names and "mummy" in member_names and "sister" in member_names

    owner_login = client.post("/api/auth/login", json={"member_name": "Saurabh", "pin": "1234"})
    assert owner_login.status_code == 200, owner_login.text
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['token']}"}

    family_login = client.post("/api/auth/login", json={"member_name": "Mummy", "pin": "0000"})
    assert family_login.status_code == 200, family_login.text
    family_headers = {"Authorization": f"Bearer {family_login.json()['token']}"}

    # 2. Test Relatives Directory Add & Modify
    rel_create = client.post(
        "/api/relatives",
        headers=owner_headers,
        json={
            "name": "Sunita Mausi",
            "relation": "Mausi",
            "side": "Maternal",
            "phone": "9811100001",
            "city": "Lucknow",
            "notes": "Very active in family circle",
        },
    )
    assert rel_create.status_code in (200, 400)
    rels = client.get("/api/relatives", headers=owner_headers).json()["relatives"]
    sunita = next(r for r in rels if r["name"] == "Sunita Mausi")
    rel_upd = client.put(
        f"/api/relatives/{sunita['id']}",
        headers=owner_headers,
        json={
            "name": "Sunita Mausi",
            "relation": "Mausi",
            "side": "Maternal",
            "phone": "9811100999",
            "city": "Lucknow",
            "notes": "Updated phone",
        },
    )
    assert rel_upd.status_code == 200
    assert rel_upd.json()["phone"] == "9811100999"

    # 3. Create Groom Profile #1 via Multimodal PDF Import
    pdf_bytes = _make_sample_biodata_pdf("Rohan Verma", "Google India", "Bangalore")
    import_res = client.post(
        "/api/imports/process",
        headers=family_headers,
        data={
            "mode": "single",
            "source_channel": "Relative",
            "source_name": "Sunita Mausi",
            "raw_text": "Sunita Mausi sent Rohan Verma's biodata for sister. IIT Delhi + Google Bangalore, 48 LPA.",
        },
        files=[("files", ("Rohan_Verma_Biodata.pdf", pdf_bytes, "application/pdf"))],
    )
    assert import_res.status_code == 200, import_res.text
    job_id = import_res.json()["jobs"][0]["job_id"]
    job_detail = client.get(f"/api/imports/{job_id}", headers=owner_headers).json()
    ext = job_detail["extracted"]

    apply_res = client.post(
        f"/api/imports/{job_id}/apply",
        headers=family_headers,
        json={
            "accepted_fields": ext["extracted_fields"],
            "positives": ext.get("positives"),
            "concerns": ext.get("concerns"),
            "missing_questions": ext.get("missing_questions"),
            "fit_summary": ext.get("fit_summary"),
            "ai_fit_score": ext.get("ai_fit_score"),
            "pre_call_brief": ext.get("pre_call_brief"),
            "create_follow_up": True,
        },
    )
    assert apply_res.status_code == 200
    profile_id = apply_res.json()["profile_id"]

    # 4. Test Smart AI Segregation & Auto-Linking to Existing Profile on a Multi-Person Upload!
    multi_upload_res = client.post(
        "/api/imports/process",
        headers=owner_headers,
        data={
            "mode": "auto",
            "source_channel": "Relative",
            "source_name": "Sunita Mausi",
            "raw_text": (
                "Update 1: Spoke to Rohan Verma's father Mr. Rajesh Verma (+91 9811122334, Google India Bangalore). "
                "Rohan is open to relocating to Gurgaon NCR and his kundli gunas matched 29/36!\n\n"
                "Update 2: Also received a brand new profile for Aditya Kapoor, Age 30, Height 5'11\", "
                "Product Manager at Microsoft Hyderabad, package 42 LPA, father Mr. Vinod Kapoor (+91 9899988776)."
            ),
        },
    )
    assert multi_upload_res.status_code == 200, multi_upload_res.text
    seg_jobs = multi_upload_res.json()["jobs"]
    assert len(seg_jobs) >= 2, f"Expected AI to segregate into at least 2 candidate jobs, got {seg_jobs}"
    rohan_job = next((j for j in seg_jobs if j.get("target_profile_id") == profile_id), None)
    assert rohan_job is not None, f"Expected AI to auto-link Rohan Verma update to existing profile #{profile_id}"

    # 5. Test Granular 1-Tap WhatsApp Templates (First-time + Consecutive Follow-Ups)
    wa_tpl = client.get(f"/api/profiles/{profile_id}/whatsapp-templates", headers=owner_headers)
    assert wa_tpl.status_code == 200
    tpl_list = wa_tpl.json()["templates"]
    categories = {t["category"] for t in tpl_list}
    assert "first_time" in categories and "follow_up" in categories
    assert len(tpl_list) >= 10

    # 6. Test 3-Stage Meeting & Call Recording Workflow + 2-Phone Reminders
    mtg_create = client.post(
        f"/api/profiles/{profile_id}/meetings",
        headers=owner_headers,
        json={
            "stage": "scheduled",
            "meeting_type": "Family Phone Call",
            "title": "Family Intro Call with Verma Family",
            "scheduled_at": "2026-11-16T19:30",
            "participants": "Saurabh, Mummy & Mr. Rajesh Verma",
            "pre_meeting_notes": "Discuss Gurgaon relocation timeline & wedding timeline",
            "reminder_minutes": 30,
            "notify_phone_1": True,
            "notify_phone_2": True,
            "send_immediate_alert": True,
        },
    )
    assert mtg_create.status_code == 200, mtg_create.text
    mtg_id = mtg_create.json()["id"]
    assert mtg_create.json().get("google_calendar_url")

    ics_res = client.get(f"/api/meetings/{mtg_id}/calendar.ics", headers=owner_headers)
    assert ics_res.status_code == 200
    assert "BEGIN:VCALENDAR" in ics_res.text

    opus_bytes = _make_sample_opus_bytes()
    complete_res = client.post(
        f"/api/meetings/{mtg_id}/complete-with-recording",
        headers=owner_headers,
        data={"post_meeting_notes": "Call went really well, families aligned on Dec/Jan meetup in Delhi."},
        files=[("recording_file", ("call_recording.opus", opus_bytes, "audio/ogg"))],
    )
    assert complete_res.status_code == 200, complete_res.text
    assert complete_res.json()["meeting"]["stage"] == "completed"
    assert complete_res.json()["meeting"]["call_recording_url"]

    # 7. Test Archive & Unarchive Profile
    arch_res = client.post(f"/api/profiles/{profile_id}/archive?archive=true", headers=owner_headers)
    assert arch_res.status_code == 200
    assert arch_res.json()["status"] == "Archived"

    active_list = client.get("/api/profiles?status=ACTIVE", headers=owner_headers).json()["profiles"]
    assert all(p["id"] != profile_id for p in active_list), "Archived profile must not appear in ACTIVE pipeline"

    unarch_res = client.post(f"/api/profiles/{profile_id}/archive?archive=false", headers=owner_headers)
    assert unarch_res.status_code == 200
    assert unarch_res.json()["status"] == "Reviewing"


def test_cloud_offline_and_outbound_mac_worker(monkeypatch):
    """
    Verifies that when the Cloud Web App runs WITHOUT ZLLAMA_API_KEY (Mac is offline/asleep):
      1. Importing biodata PDFs/text still works 100% immediately via the Offline Smart Parser.
      2. Saving the profile, Side-by-Side Compare, Meeting Quick-Parse, and 1-Tap WhatsApp templates all work offline.
      3. The import job is queued in `worker_tasks`.
      4. When the Outbound-Only Mac AI Worker polls `/api/worker/poll` and posts to `/api/worker/tasks/{id}/complete`,
         the saved profile is automatically enriched in-place!
    """
    import app.services.ai_extractor as ai_mod
    from app.config import WORKER_SHARED_SECRET

    init_db()
    client = TestClient(app)

    family_login = client.post("/api/auth/login", json={"member_name": "Sister", "pin": "0000"})
    assert family_login.status_code == 200
    family_headers = {"Authorization": f"Bearer {family_login.json()['token']}"}

    # Simulate Cloud Web App mode (No ZLLAMA_API_KEY on cloud server, Mac is asleep)
    monkeypatch.setattr(ai_mod, "ZLLAMA_API_KEY", "")

    pdf_bytes = _make_sample_biodata_pdf("Vikramaditya Singh", "Amazon India", "Hyderabad")
    imp_res = client.post(
        "/api/imports/process",
        headers=family_headers,
        data={
            "mode": "single",
            "source_channel": "Relative",
            "source_name": "Sunita Mausi",
            "raw_text": "Name: Vikramaditya Singh\nAge: 29\nHeight: 5'11\"\nGotra: Bharadwaj\nAnnual Package: 52 LPA\nCurrent Location: Hyderabad\nContact: +91 9811155667",
        },
        files=[("files", ("Vikram_Biodata.pdf", pdf_bytes, "application/pdf"))],
    )
    assert imp_res.status_code == 200, imp_res.text
    job_info = imp_res.json()["jobs"][0]
    assert job_info["pending_mac_ai"] is True
    assert "Vikramaditya" in job_info["candidate_name"]

    job_id = job_info["job_id"]
    job_detail = client.get(f"/api/imports/{job_id}", headers=family_headers).json()
    ext = job_detail["extracted"]
    assert ext["extracted_fields"]["annual_ctc"] in ("48 LPA", "52 LPA")
    assert ext["extracted_fields"].get("avatar_url"), "Portrait photo must still extract offline!"

    # Sister approves & saves the profile while Mac is still asleep
    apply_res = client.post(
        f"/api/imports/{job_id}/apply",
        headers=family_headers,
        json={"accepted_fields": ext["extracted_fields"], "create_follow_up": True},
    )
    assert apply_res.status_code == 200
    pid = apply_res.json()["profile_id"]

    # Meeting Quick-Parse works offline
    qp = client.post(
        "/api/meetings/quick-parse",
        headers=family_headers,
        json={"text": "Video call with Vikram family tomorrow at 8:00 PM"},
    )
    assert qp.status_code == 200
    assert qp.json()["meeting_type"] == "Video Call"

    # Now Mac wakes up and Outbound Worker polls /api/worker/poll!
    worker_headers = {"X-Worker-Secret": WORKER_SHARED_SECRET}
    poll_res = client.post("/api/worker/poll", headers=worker_headers, json={"hostname": "H0KGC423TJ"})
    assert poll_res.status_code == 200
    task = poll_res.json()["task"]
    assert task is not None
    tid = task["id"]

    # Worker submits deep zllama AI result back over outbound HTTPS
    comp_res = client.post(
        f"/api/worker/tasks/{tid}/complete",
        headers=worker_headers,
        json={
            "ai_bundle": {
                "extracted_fields": {**ext["extracted_fields"], "relocation_openness": "Open to Gurgaon & Bangalore"},
                "ai_fit_score": 91,
                "fit_summary": "Enriched by Mac AI Worker (gpt-5.4 + claude-sonnet-4-6): Strong match.",
                "positives": ["IIT Delhi + MBA", "Open to NCR relocation"],
                "concerns": [],
                "missing_questions": ["Confirm exact wedding timeline"],
                "pre_call_brief": "• Enriched Pre-Call Brief from Mac AI Worker",
                "models_used": {"vision_extraction": "gpt-5.4", "reasoning_advisor": "claude-sonnet-4-6"},
            }
        },
    )
    assert comp_res.status_code == 200

    # Verify the already-saved profile was automatically enriched in-place!
    enriched_prof = client.get(f"/api/profiles/{pid}", headers=family_headers).json()
    assert enriched_prof["ai_fit_score"] == 91
    assert "Enriched by Mac AI Worker" in enriched_prof["fit_summary"]
    assert enriched_prof["relocation_openness"] == "Open to Gurgaon & Bangalore"

