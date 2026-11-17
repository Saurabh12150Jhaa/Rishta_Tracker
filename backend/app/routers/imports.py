import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from ..auth import get_current_member, sanitize_profile_for_member
from ..db import get_conn, utc_now
from ..models import ApplyImportRequest, PROFILE_EDITABLE_FIELDS
from ..services.ai_extractor import (
    build_disambiguation_tag,
    compute_embedding,
    extract_rishta_bundle,
    segregate_and_match_upload_bundle,
    split_whatsapp_chat_candidates,
    transcribe_voice_note_hinglish,
)
from ..services.dedupe import build_profile_embedding_text, find_duplicate_candidates
from ..services.media_proc import (
    image_bytes_to_data_url,
    parse_structured_file_to_text,
    process_pdf_biodata,
    save_uploaded_bytes,
    transcode_audio_to_mp3_b64,
    unpack_whatsapp_zip,
)
from .worker import enqueue_worker_task, is_remote_mac_worker_online, wait_for_worker_task

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _record_media_asset(
    conn,
    asset_type: str,
    file_name: str,
    file_path: Path,
    url_path: str,
    mime_type: str,
    uploaded_by: str,
    profile_id: Optional[int] = None,
    import_job_id: Optional[int] = None,
    transcript_or_ocr: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO media_assets (
            profile_id, import_job_id, asset_type, file_name, file_path, url_path,
            mime_type, transcript_or_ocr, uploaded_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            import_job_id,
            asset_type,
            file_name,
            str(file_path),
            url_path,
            mime_type,
            transcript_or_ocr,
            uploaded_by,
            utc_now(),
        ),
    )
    return cur.lastrowid


def _create_single_import_job(
    raw_text: str,
    pdf_items: list[tuple[Path, str, str]],
    image_items: list[tuple[Path, str, str]],
    audio_items: list[tuple[Path, str, str]],
    source_name: Optional[str],
    source_channel: Optional[str],
    target_profile_id: Optional[int],
    member_name: str,
    mode_label: str = "single",
    precomputed_voice_transcript: str = "",
    ai_auto_link_reason: Optional[str] = None,
    segregation_model: Optional[str] = None,
) -> dict:
    conn = get_conn()
    existing_profile = None
    if target_profile_id:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (target_profile_id,)).fetchone()
        if row:
            existing_profile = dict(row)

    pdf_texts: list[str] = []
    image_data_urls: list[str] = []
    audio_mp3_b64_list: list[str] = []
    candidate_photo_url: Optional[str] = None
    asset_records: list[dict] = []

    for pdf_path, url_path, orig_name in pdf_items:
        pdf_res = process_pdf_biodata(pdf_path)
        if pdf_res["text"]:
            pdf_texts.append(pdf_res["text"])
        image_data_urls.extend(pdf_res["page_images"])
        if pdf_res["portrait_url"] and not candidate_photo_url:
            candidate_photo_url = pdf_res["portrait_url"]
        asset_records.append(
            {
                "asset_type": "biodata_pdf",
                "file_name": orig_name,
                "file_path": pdf_path,
                "url_path": url_path,
                "mime_type": "application/pdf",
                "transcript_or_ocr": pdf_res["text"][:4000] if pdf_res["text"] else None,
            }
        )

    for img_path, url_path, orig_name in image_items:
        content = img_path.read_bytes()
        image_data_urls.append(image_bytes_to_data_url(content))
        if not candidate_photo_url:
            candidate_photo_url = url_path
        asset_records.append(
            {
                "asset_type": "photo",
                "file_name": orig_name,
                "file_path": img_path,
                "url_path": url_path,
                "mime_type": "image/jpeg",
                "transcript_or_ocr": None,
            }
        )

    for aud_path, url_path, orig_name in audio_items:
        if not precomputed_voice_transcript:
            mp3_b64 = transcode_audio_to_mp3_b64(aud_path)
            if mp3_b64:
                audio_mp3_b64_list.append(mp3_b64)
        asset_records.append(
            {
                "asset_type": "voice_note",
                "file_name": orig_name,
                "file_path": aud_path,
                "url_path": url_path,
                "mime_type": "audio/mpeg",
                "transcript_or_ocr": precomputed_voice_transcript or None,
            }
        )

    effective_raw_text = raw_text
    if precomputed_voice_transcript:
        effective_raw_text = f"{raw_text}\n\n=== Voice Note Transcript ===\n{precomputed_voice_transcript}".strip()

    ai_bundle = extract_rishta_bundle(
        raw_text=effective_raw_text,
        pdf_texts=pdf_texts,
        image_data_urls=image_data_urls,
        audio_mp3_b64_list=audio_mp3_b64_list,
        source_name=source_name,
        source_channel=source_channel,
        existing_profile=existing_profile,
    )
    if precomputed_voice_transcript and not ai_bundle.get("voice_transcript"):
        ai_bundle["voice_transcript"] = precomputed_voice_transcript
    if segregation_model:
        ai_bundle.setdefault("models_used", {})["segregation_and_linking"] = segregation_model

    if candidate_photo_url and not ai_bundle["extracted_fields"].get("avatar_url"):
        ai_bundle["extracted_fields"]["avatar_url"] = candidate_photo_url

    duplicates = find_duplicate_candidates(
        ai_bundle["extracted_fields"],
        candidate_embedding=ai_bundle.get("embedding"),
        exclude_profile_id=None,
    )
    ai_bundle["duplicate_matches"] = duplicates
    ai_bundle["candidate_photo_url"] = candidate_photo_url

    # Auto-link to existing profile if high-confidence duplicate/match detected and not already linked
    if not target_profile_id and duplicates and duplicates[0]["confidence"] >= 0.72:
        top_dup = duplicates[0]
        target_profile_id = top_dup["profile_id"]
        ai_auto_link_reason = (
            f"Auto-linked to Existing Profile #{top_dup['profile_id']} ({top_dup['full_name']}) — "
            f"{', '.join(top_dup.get('reasons') or ['High similarity'])}"
        )

    ai_bundle["ai_auto_link_reason"] = ai_auto_link_reason

    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO import_jobs (
            mode, target_profile_id, status, source_name, source_channel,
            raw_text, voice_transcript, extracted_json, created_by_member, created_at
        ) VALUES (?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mode_label,
            target_profile_id,
            source_name or ai_bundle["extracted_fields"].get("source_name"),
            source_channel or ai_bundle["extracted_fields"].get("source_channel") or "Relative",
            raw_text,
            ai_bundle.get("voice_transcript") or "",
            json.dumps(ai_bundle),
            member_name,
            now,
        ),
    )
    job_id = cur.lastrowid

    media_ids = []
    for rec in asset_records:
        transcript_val = rec["transcript_or_ocr"]
        if rec["asset_type"] == "voice_note" and ai_bundle.get("voice_transcript"):
            transcript_val = ai_bundle["voice_transcript"]
        mid = _record_media_asset(
            conn=conn,
            asset_type=rec["asset_type"],
            file_name=rec["file_name"],
            file_path=rec["file_path"],
            url_path=rec["url_path"],
            mime_type=rec["mime_type"],
            uploaded_by=member_name,
            profile_id=target_profile_id,
            import_job_id=job_id,
            transcript_or_ocr=transcript_val,
        )
        media_ids.append(mid)

    ai_bundle["media_asset_ids"] = media_ids
    conn.execute("UPDATE import_jobs SET extracted_json = ? WHERE id = ?", (json.dumps(ai_bundle), job_id))
    conn.commit()
    conn.close()

    # If running on the Cloud Web App (where local zllama wasn't available), queue for Outbound Mac AI Worker!
    if ai_bundle.get("pending_mac_ai"):
        task_id = enqueue_worker_task(
            "extract_import_job",
            job_id,
            {
                "job_id": job_id,
                "raw_text": raw_text,
                "pdf_texts": pdf_texts,
                "media_asset_ids": media_ids,
                "source_name": source_name,
                "source_channel": source_channel,
                "target_profile_id": target_profile_id,
                "candidate_photo_url": candidate_photo_url,
            },
        )
        remote_online, _, _ = is_remote_mac_worker_online()
        if remote_online:
            live_res = wait_for_worker_task(task_id, timeout_seconds=38.0)
            if live_res:
                ai_bundle = live_res
                duplicates = ai_bundle.get("duplicate_matches") or duplicates

    return {
        "job_id": job_id,
        "status": "pending_review",
        "target_profile_id": target_profile_id,
        "candidate_name": ai_bundle["extracted_fields"].get("full_name") or "New Candidate",
        "disambiguation_tag": ai_bundle["extracted_fields"].get("disambiguation_tag"),
        "ai_fit_score": ai_bundle.get("ai_fit_score"),
        "duplicate_matches": duplicates,
        "gotra_clash_alert": ai_bundle.get("gotra_clash_alert"),
        "models_used": ai_bundle.get("models_used"),
        "pending_mac_ai": bool(ai_bundle.get("pending_mac_ai")),
    }


@router.post("/process")
async def process_import(
    mode: str = Form(default="single"),
    target_profile_id: Optional[int] = Form(default=None),
    raw_text: str = Form(default=""),
    source_name: Optional[str] = Form(default=None),
    source_channel: Optional[str] = Form(default="Relative"),
    files: list[UploadFile] = File(default=[]),
    member: dict = Depends(get_current_member),
):
    pdf_items: list[tuple[Path, str, str]] = []
    image_items: list[tuple[Path, str, str]] = []
    audio_items: list[tuple[Path, str, str]] = []
    zip_chat_texts: list[str] = []

    for up in files:
        if not up.filename:
            continue
        content = await up.read()
        if not content:
            continue
        ext = Path(up.filename).suffix.lower()
        ctype = (up.content_type or "").lower()

        if ext == ".zip" or "zip" in ctype:
            zip_path, _ = save_uploaded_bytes(content, up.filename, "imports")
            unpacked = unpack_whatsapp_zip(zip_path)
            if unpacked["chat_text"]:
                zip_chat_texts.append(unpacked["chat_text"])
            pdf_items.extend(unpacked["pdfs"])
            image_items.extend(unpacked["images"])
            audio_items.extend(unpacked["audios"])
        elif ext == ".pdf" or "pdf" in ctype:
            p, u = save_uploaded_bytes(content, up.filename, "biodata")
            pdf_items.append((p, u, up.filename))
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic") or ctype.startswith("image/"):
            p, u = save_uploaded_bytes(content, up.filename, "photos")
            image_items.append((p, u, up.filename))
        elif ext in (".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".webm", ".amr") or ctype.startswith("audio/"):
            p, u = save_uploaded_bytes(content, up.filename, "voice")
            audio_items.append((p, u, up.filename))
        elif ext in (".vcf", ".csv", ".tsv", ".docx", ".xlsx"):
            parsed_doc = parse_structured_file_to_text(content, up.filename)
            if parsed_doc:
                zip_chat_texts.append(parsed_doc)

    combined_text = "\n\n".join(t for t in [raw_text, *zip_chat_texts] if t and t.strip())
    if not combined_text and not pdf_items and not image_items and not audio_items:
        raise HTTPException(status_code=400, detail="Please provide WhatsApp text, a biodata PDF, photo/diary image, voice note, .vcf/.csv/.xlsx/.docx, or .zip export.")

    created_jobs = []

    # Smart AI Text/PDF Segregation when multiple PDFs, .zip, or long text/voice are uploaded
    # (Note: when images/diary pages are uploaded without multi-PDFs, _create_single_import_job handles Vision + Bulk Register extraction directly!)
    if (
        not target_profile_id
        and not image_items
        and (
            len(pdf_items) > 1
            or len(zip_chat_texts) > 0
            or len(audio_items) > 0
            or len(combined_text) > 80
        )
    ):
        conn = get_conn()
        existing_rows = [dict(r) for r in conn.execute("SELECT * FROM profiles").fetchall()]
        conn.close()

        pdf_summaries = []
        for idx, (pdf_path, _, orig_name) in enumerate(pdf_items):
            try:
                p_info = process_pdf_biodata(pdf_path, max_pages=2)
                pdf_summaries.append({"pdf_index": idx, "file_name": orig_name, "text": (p_info["text"] or "")[:3000]})
            except Exception:
                pdf_summaries.append({"pdf_index": idx, "file_name": orig_name, "text": ""})

        audio_transcripts = []
        for idx, (aud_path, _, orig_name) in enumerate(audio_items):
            mp3_b64 = transcode_audio_to_mp3_b64(aud_path)
            t_str = ""
            if mp3_b64:
                try:
                    t_str, _ = transcribe_voice_note_hinglish(mp3_b64, context_hint=source_name or "")
                except Exception:
                    t_str = ""
            audio_transcripts.append({"audio_index": idx, "file_name": orig_name, "transcript": t_str})

        image_names = [{"image_index": idx, "file_name": orig_name} for idx, (_, _, orig_name) in enumerate(image_items)]

        try:
            segregated_list, seg_model = segregate_and_match_upload_bundle(
                raw_text=combined_text,
                pdf_summaries=pdf_summaries,
                audio_transcripts=audio_transcripts,
                image_names=image_names,
                existing_profiles=existing_rows,
            )
        except Exception:
            segregated_list, seg_model = [], None

        if segregated_list and (len(segregated_list) > 1 or segregated_list[0].get("matched_existing_profile_id")):
            valid_profile_ids = {r["id"] for r in existing_rows}

            def _build_cand_job(cand: dict) -> dict:
                matched_id = cand.get("matched_existing_profile_id")
                conf = float(cand.get("match_confidence") or 0.0)
                if matched_id not in valid_profile_ids or conf < 0.65:
                    matched_id = None

                p_indices = [i for i in (cand.get("pdf_indices") or []) if isinstance(i, int) and 0 <= i < len(pdf_items)]
                i_indices = [i for i in (cand.get("image_indices") or []) if isinstance(i, int) and 0 <= i < len(image_items)]
                a_indices = [i for i in (cand.get("audio_indices") or []) if isinstance(i, int) and 0 <= i < len(audio_items)]

                if len(segregated_list) == 1:
                    if not p_indices and pdf_items:
                        p_indices = list(range(len(pdf_items)))
                    if not i_indices and image_items:
                        i_indices = list(range(len(image_items)))
                    if not a_indices and audio_items:
                        a_indices = list(range(len(audio_items)))

                cand_pdfs = [pdf_items[i] for i in p_indices]
                cand_imgs = [image_items[i] for i in i_indices]
                cand_auds = [audio_items[i] for i in a_indices]
                cand_voice_txt = cand.get("segregated_voice_transcript") or "\n".join(
                    audio_transcripts[i]["transcript"] for i in a_indices if audio_transcripts[i].get("transcript")
                )

                return _create_single_import_job(
                    raw_text=cand.get("segregated_text") or combined_text,
                    pdf_items=cand_pdfs,
                    image_items=cand_imgs,
                    audio_items=cand_auds,
                    source_name=source_name or cand.get("source_name_hint"),
                    source_channel=source_channel,
                    target_profile_id=matched_id,
                    member_name=member["name"],
                    mode_label="ai_segregated" if len(segregated_list) > 1 else mode,
                    precomputed_voice_transcript=cand_voice_txt,
                    ai_auto_link_reason=cand.get("match_reason") if matched_id else None,
                    segregation_model=seg_model,
                )

            with ThreadPoolExecutor(max_workers=min(4, len(segregated_list))) as ex:
                created_jobs = list(ex.map(_build_cand_job, segregated_list))
            return {"mode": "ai_segregated", "jobs": created_jobs}

    job = _create_single_import_job(
        raw_text=combined_text,
        pdf_items=pdf_items,
        image_items=image_items,
        audio_items=audio_items,
        source_name=source_name,
        source_channel=source_channel,
        target_profile_id=target_profile_id,
        member_name=member["name"],
        mode_label=mode,
    )
    return {"mode": mode, "jobs": [job]}


@router.get("")
def list_import_jobs(status: Optional[str] = None, member: dict = Depends(get_current_member)):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM import_jobs WHERE status = ? ORDER BY id DESC LIMIT 50",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM import_jobs ORDER BY id DESC LIMIT 50").fetchall()

    out = []
    for r in rows:
        item = dict(r)
        try:
            item["extracted"] = json.loads(item.pop("extracted_json", "{}"))
        except Exception:
            item["extracted"] = {}
        item["extracted"].pop("embedding", None)
        out.append(item)
    conn.close()
    return {"jobs": out}


@router.get("/{job_id}")
def get_import_job(job_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Import job not found")

    item = dict(row)
    try:
        extracted = json.loads(item.pop("extracted_json", "{}"))
    except Exception:
        extracted = {}
    extracted.pop("embedding", None)
    item["extracted"] = extracted

    target_profile = None
    if item.get("target_profile_id"):
        p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (item["target_profile_id"],)).fetchone()
        if p_row:
            target_profile = sanitize_profile_for_member(dict(p_row), member)

    assets = conn.execute("SELECT * FROM media_assets WHERE import_job_id = ? ORDER BY id ASC", (job_id,)).fetchall()
    all_profs = conn.execute(
        "SELECT id, full_name, current_city, company, occupation, source_name, status FROM profiles ORDER BY updated_at DESC"
    ).fetchall()
    pending_jobs = conn.execute(
        "SELECT id, mode, target_profile_id, source_name, extracted_json FROM import_jobs WHERE status = 'pending_review' ORDER BY id ASC"
    ).fetchall()
    pending_queue = []
    for pj in pending_jobs:
        try:
            p_ext = json.loads(pj["extracted_json"] or "{}")
            cname = (p_ext.get("extracted_fields") or {}).get("full_name") or "Candidate"
        except Exception:
            cname = "Candidate"
        pending_queue.append(
            {
                "id": pj["id"],
                "candidate_name": cname,
                "target_profile_id": pj["target_profile_id"],
                "mode": pj["mode"],
            }
        )

    item["media_assets"] = [dict(a) for a in assets]
    item["target_profile"] = target_profile
    item["all_existing_profiles"] = [dict(p) for p in all_profs]
    item["pending_queue"] = pending_queue
    conn.close()
    return item


@router.post("/{job_id}/apply")
def apply_import_job(job_id: int, req: ApplyImportRequest, member: dict = Depends(get_current_member)):
    conn = get_conn()
    job_row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Import job not found")

    job = dict(job_row)
    try:
        extracted = json.loads(job.get("extracted_json") or "{}")
    except Exception:
        extracted = {}

    # If this import job is a Multi-Candidate Bulk List, always expand into individual profiles!
    if isinstance(extracted.get("bulk_candidates"), list) and len(extracted["bulk_candidates"]) >= 2:
        conn.close()
        res = apply_bulk_register_import_job(job_id, {"rows": extracted["bulk_candidates"]}, member)
        first_pid = (res.get("created_profile_ids") or res.get("updated_profile_ids") or [1])[0]
        return {"ok": True, "profile_id": first_pid, **res}

    base_fields = dict(extracted.get("extracted_fields") or {})
    if req.accepted_fields:
        base_fields = dict(req.accepted_fields)

    target_id = req.target_profile_id or job.get("target_profile_id")
    now = utc_now()

    positives = req.positives if req.positives is not None else (extracted.get("positives") or [])
    concerns = req.concerns if req.concerns is not None else (extracted.get("concerns") or [])
    missing_q = req.missing_questions if req.missing_questions is not None else (extracted.get("missing_questions") or [])
    fit_summary = req.fit_summary if req.fit_summary is not None else (extracted.get("fit_summary") or "")
    ai_fit_score = req.ai_fit_score if req.ai_fit_score is not None else extracted.get("ai_fit_score")
    pre_call_brief = req.pre_call_brief if req.pre_call_brief is not None else (extracted.get("pre_call_brief") or "")

    if target_id:
        existing_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (target_id,)).fetchone()
        if not existing_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Target profile to merge into was not found.")
        existing = dict(existing_row)

        updates = {}
        for k, v in base_fields.items():
            if k in PROFILE_EDITABLE_FIELDS and v not in (None, ""):
                if k == "private_notes" and member["role"] != "owner":
                    continue
                updates[k] = v

        merged_for_tag = {**existing, **updates}
        updates["disambiguation_tag"] = build_disambiguation_tag(merged_for_tag)
        if fit_summary:
            updates["fit_summary"] = fit_summary
        if ai_fit_score is not None:
            updates["ai_fit_score"] = ai_fit_score
        if pre_call_brief:
            updates["pre_call_brief"] = pre_call_brief
        updates["positives_json"] = json.dumps(positives)
        updates["concerns_json"] = json.dumps(concerns)
        updates["missing_questions_json"] = json.dumps(missing_q)

        emb_vec = extracted.get("embedding")
        if not emb_vec:
            emb_vec, _ = compute_embedding(build_profile_embedding_text(merged_for_tag))
        if emb_vec:
            updates["embedding_json"] = json.dumps(emb_vec)

        updates["updated_at"] = now
        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), target_id))
        profile_id = target_id
    else:
        insert_data = {
            col: base_fields.get(col)
            for col in PROFILE_EDITABLE_FIELDS
            if base_fields.get(col) not in (None, "")
        }
        if not insert_data.get("full_name"):
            insert_data["full_name"] = "Unnamed Prospect"
        if not insert_data.get("status"):
            insert_data["status"] = extracted.get("suggested_status") or "Reviewing"
        if not insert_data.get("ball_in_court"):
            insert_data["ball_in_court"] = extracted.get("suggested_ball_in_court") or "us"
        if not insert_data.get("source_name") and job.get("source_name"):
            insert_data["source_name"] = job["source_name"]
        if not insert_data.get("source_channel") and job.get("source_channel"):
            insert_data["source_channel"] = job["source_channel"]

        insert_data["disambiguation_tag"] = build_disambiguation_tag(insert_data)
        insert_data["fit_summary"] = fit_summary
        insert_data["ai_fit_score"] = ai_fit_score
        insert_data["pre_call_brief"] = pre_call_brief
        insert_data["positives_json"] = json.dumps(positives)
        insert_data["concerns_json"] = json.dumps(concerns)
        insert_data["missing_questions_json"] = json.dumps(missing_q)

        emb_vec = extracted.get("embedding")
        if not emb_vec:
            emb_vec, _ = compute_embedding(build_profile_embedding_text(insert_data))
        if emb_vec:
            insert_data["embedding_json"] = json.dumps(emb_vec)

        insert_data["created_by_member"] = member["name"]
        insert_data["created_at"] = now
        insert_data["updated_at"] = now

        cols = list(insert_data.keys())
        placeholders = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(insert_data[c] for c in cols),
        )
        profile_id = cur.lastrowid

    conn.execute("UPDATE media_assets SET profile_id = ? WHERE import_job_id = ?", (profile_id, job_id))

    summary_text = req.interaction_note or extracted.get("interaction_summary") or "Imported WhatsApp / Biodata details"
    conn.execute(
        """
        INSERT INTO interactions (
            profile_id, interaction_type, title, summary, raw_text, transcript,
            visibility, created_by_member, occurred_at, created_at
        ) VALUES (?, 'whatsapp_import', ?, ?, ?, ?, 'shared', ?, ?, ?)
        """,
        (
            profile_id,
            f"AI Import by {member['name']}",
            summary_text,
            job.get("raw_text") or "",
            job.get("voice_transcript") or "",
            member["name"],
            now,
            now,
        ),
    )

    if req.create_follow_up:
        sugg = extracted.get("suggested_follow_up") or {}
        f_task = req.follow_up_task or sugg.get("task") or "Review profile & discuss next step with family"
        due_date = req.follow_up_due_date
        if not due_date:
            due_days = int(sugg.get("due_days") or 2)
            due_date = (datetime.now(timezone.utc) + timedelta(days=due_days)).strftime("%Y-%m-%d")
        conn.execute(
            """
            INSERT INTO follow_ups (
                profile_id, task, due_date, assigned_to, ball_in_court,
                completed, created_by_member, created_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                profile_id,
                f_task,
                due_date,
                sugg.get("assigned_to") or member["name"],
                extracted.get("suggested_ball_in_court") or "us",
                member["name"],
                now,
            ),
        )

    conn.execute(
        "UPDATE import_jobs SET status = 'applied', target_profile_id = ? WHERE id = ?",
        (profile_id, job_id),
    )

    # Auto-register referring relative/mediator in the Relatives Directory if not already present
    src_name = (base_fields.get("source_name") or job.get("source_name") or "").strip()
    if src_name:
        src_channel = (base_fields.get("source_channel") or job.get("source_channel") or "Relative").strip()
        src_phone = (base_fields.get("source_phone") or "").strip()
        conn.execute(
            """
            INSERT OR IGNORE INTO relatives (name, relation, side, phone, city, notes, created_at, updated_at)
            VALUES (?, ?, 'Family', ?, '', 'Added from profile import', ?, ?)
            """,
            (src_name, src_channel, src_phone, now, now),
        )

    conn.commit()
    conn.close()
    return {"ok": True, "profile_id": profile_id}


@router.post("/{job_id}/apply-batch")
def apply_bulk_register_import_job(
    job_id: int,
    payload: dict,
    member: dict = Depends(get_current_member),
):
    """
    Applies a Multi-Row Handwritten Diary / Register / Spreadsheet batch import in 1 click:
      - Updates existing profiles for rows where `matched_profile_id` is set.
      - Creates new profiles for rows where `matched_profile_id` is null.
    """
    conn = get_conn()
    job_row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Import job not found")

    job = dict(job_row)
    try:
        extracted = json.loads(job.get("extracted_json") or "{}")
    except Exception:
        extracted = {}

    rows_to_apply = payload.get("rows")
    if rows_to_apply is None:
        rows_to_apply = [r for r in (extracted.get("bulk_candidates") or []) if r.get("selected", True)]

    now = utc_now()
    created_ids: list[int] = []
    updated_ids: list[int] = []

    for r in rows_to_apply:
        if not r.get("selected", True):
            continue
        fields = dict(r.get("fields") or {})
        name = (fields.get("full_name") or "").strip()
        if not name:
            continue

        matched_id = r.get("matched_profile_id")
        if matched_id:
            ex_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (matched_id,)).fetchone()
            if ex_row:
                ex = dict(ex_row)
                updates = {}
                for k, v in fields.items():
                    if k in PROFILE_EDITABLE_FIELDS and v not in (None, "") and not ex.get(k):
                        updates[k] = v
                merged = {**ex, **updates}
                updates["disambiguation_tag"] = build_disambiguation_tag(merged)
                updates["updated_at"] = now
                set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
                conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), matched_id))
                updated_ids.append(matched_id)
                continue

        # Create New Profile for non-existing candidate
        insert_data = {
            col: fields.get(col)
            for col in PROFILE_EDITABLE_FIELDS
            if fields.get(col) not in (None, "")
        }
        insert_data["full_name"] = name
        insert_data["gender"] = insert_data.get("gender") or "Male"
        insert_data["status"] = insert_data.get("status") or ("Passed" if r.get("is_crossed_out") else "New")
        insert_data["ball_in_court"] = insert_data.get("ball_in_court") or ("closed" if r.get("is_crossed_out") else "us")
        if r.get("is_crossed_out") and not insert_data.get("pass_reason"):
            insert_data["pass_reason"] = "Crossed out in family diary register"
        insert_data["source_name"] = insert_data.get("source_name") or job.get("source_name") or "Family Diary"
        insert_data["source_channel"] = insert_data.get("source_channel") or job.get("source_channel") or "Relative"
        insert_data["disambiguation_tag"] = build_disambiguation_tag(insert_data)
        insert_data["fit_summary"] = (
            f"Imported from family diary/register ({r.get('raw_row_notes') or insert_data['disambiguation_tag']})."
        )
        insert_data["ai_fit_score"] = 45 if r.get("is_crossed_out") else 78
        insert_data["positives_json"] = json.dumps(
            [x for x in [insert_data.get("occupation"), insert_data.get("current_city"), insert_data.get("siblings_details")] if x]
        )
        insert_data["concerns_json"] = json.dumps(
            ["Crossed out in family diary"] if r.get("is_crossed_out") else []
        )
        insert_data["missing_questions_json"] = json.dumps(
            ["Ask for full Biodata PDF & Kundli birth details (DOB/TOB/POB)"]
        )
        insert_data["created_by_member"] = member["name"]
        insert_data["created_at"] = now
        insert_data["updated_at"] = now

        cols = list(insert_data.keys())
        placeholders = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(insert_data[c] for c in cols),
        )
        created_ids.append(cur.lastrowid)

    conn.execute("UPDATE import_jobs SET status = 'applied' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "created_count": len(created_ids),
        "updated_count": len(updated_ids),
        "created_profile_ids": created_ids,
        "updated_profile_ids": updated_ids,
    }


@router.post("/{job_id}/reject")
def reject_import_job(job_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    conn.execute("UPDATE import_jobs SET status = 'rejected' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
