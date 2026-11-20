import pytest

from app.routers import imports as imports_router
from app.services.dedupe import find_duplicate_candidates
from app.services.matrimony_links import parse_matrimony_reference
from app.services.offline_extractor import offline_extract_rishta_bundle
from conftest import insert_profile


@pytest.mark.parametrize(
    "text,platform,pid",
    [
        ("https://www.jeevansathi.com/profile/viewprofile.php?profilechecksum=abc123i4567890&stype=N", "Jeevansathi", "abc123i4567890"),
        ("Check this https://www.jeevansathi.com/profile/viewprofile.php?username=ABCD1234 nice", "Jeevansathi", "ABCD1234"),
        ("https://jeevansathi.com/profile/JS5551234.", "Jeevansathi", "JS5551234"),
        ("Profile ID: XYZ98765 on Jeevansathi", "Jeevansathi", "XYZ98765"),
        ("JS ID: 5551234 shared by mausi", "Jeevansathi", "5551234"),
        ("www.shaadi.com/profile/view/SH1234567?x=1", "Shaadi", "SH1234567"),
        ("https://www.bharatmatrimony.com/profile?matriid=M1234567", "BharatMatrimony", "M1234567"),
    ],
)
def test_parse_matrimony_reference(text, platform, pid):
    ref = parse_matrimony_reference(text)
    assert ref and ref["platform"] == platform and ref["profile_id"] == pid


def test_parse_url_without_id_and_non_matches():
    ref = parse_matrimony_reference("see https://www.jeevansathi.com/")
    assert ref and ref["platform"] == "Jeevansathi" and ref["profile_id"] is None
    assert ref["url"].startswith("https://www.jeevansathi.com")
    assert parse_matrimony_reference("https://example.com/profile/12345") is None
    assert parse_matrimony_reference("Profile ID: 12345 only") is None
    assert parse_matrimony_reference("") is None


def test_exact_external_id_is_top_match(iso):
    insert_profile("Someone Else", external_platform="Shaadi", external_profile_id="ABCD1234")
    insert_profile("Right Person", external_platform="Jeevansathi", external_profile_id="abcd1234")
    matches = find_duplicate_candidates(
        {"full_name": "Unrelated Name", "external_platform": "Jeevansathi", "external_profile_id": "ABCD1234"}
    )
    assert matches[0]["full_name"] == "Right Person"
    assert matches[0]["confidence"] == 1.0
    assert all(m["full_name"] != "Someone Else" for m in matches)


def _offline_only(**kw):
    return offline_extract_rishta_bundle(
        raw_text=kw.get("raw_text", ""),
        pdf_texts=kw.get("pdf_texts"),
        source_name=kw.get("source_name"),
        source_channel=kw.get("source_channel"),
        existing_profile=kw.get("existing_profile"),
    )


def test_share_target_sets_jeevansathi_source(iso, monkeypatch):
    monkeypatch.setattr(imports_router, "extract_rishta_bundle", _offline_only)
    r = iso.post(
        "/share-target",
        data={"text": "Profile on https://www.jeevansathi.com/profile/viewprofile.php?username=ABCD1234"},
        cookies={"rishta_session": iso.token},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "review_job=" in r.headers["location"]
    job_id = int(r.headers["location"].split("review_job=")[1])
    job = iso.get(f"/api/imports/{job_id}", headers=iso.member_headers).json()
    assert job["source_name"] == "Jeevansathi"
    assert job["source_channel"] == "Matrimonial App"
    fields = job["extracted"]["extracted_fields"]
    assert fields["external_profile_id"] == "ABCD1234" and fields["external_platform"] == "Jeevansathi"
    assert fields["external_profile_url"].startswith("https://www.jeevansathi.com")


def test_import_process_sets_source_for_matrimony_text(iso, monkeypatch):
    monkeypatch.setattr(imports_router, "extract_rishta_bundle", _offline_only)
    r = iso.post(
        "/api/imports/process",
        data={"mode": "single", "raw_text": "Profile ID: XYZ98765 Jeevansathi", "source_channel": "Relative"},
        headers=iso.member_headers,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["jobs"][0]["job_id"]
    job = iso.get(f"/api/imports/{job_id}", headers=iso.member_headers).json()
    assert job["source_name"] == "Jeevansathi"
    assert job["extracted"]["extracted_fields"]["external_profile_id"] == "XYZ98765"


def test_offline_extractor_makes_no_ai_judgments(iso):
    out = offline_extract_rishta_bundle(raw_text="Name: Rohan Verma\nCity: Gurgaon\nPackage: 35 LPA")
    assert out["ai_fit_score"] is None
    assert out["suggested_status"] is None
    assert out["suggested_follow_up"] is None
    assert out["pending_mac_ai"] is True
    assert out["fit_summary"] == "Pending Mac AI review"
    assert out["missing_questions"]
    assert out["extracted_fields"]["annual_ctc"]
