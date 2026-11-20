import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import DB_PATH, MEDIA_DIR, OWNER_DEFAULT_PIN, FAMILY_DEFAULT_PIN, DEFAULT_AI_PRESET


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"rishta-pin:{pin.strip()}".encode()).hexdigest()


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


DEFAULT_SETTINGS = {
    "ai_preset": DEFAULT_AI_PRESET,
    "partner_preferences": {
        "preferred_age_min": 27,
        "preferred_age_max": 33,
        "preferred_height_min": "5'7\"",
        "preferred_cities": ["Gurgaon", "Noida", "Delhi NCR", "Bangalore", "Mumbai", "Hyderabad"],
        "diet_preference": "Vegetarian / Eggetarian preferred",
        "working_preference": "Well-educated, stable career & progressive outlook",
        "excluded_gotras": [],
        "dealbreakers": ["Smoker", "Not supportive of sister's career"],
        "family_values_note": "Looking for a warm, educated groom & respectful family for Saurabh's sister",
    },
    "my_outbound_pack": {
        "my_full_name": "Sister's Profile",
        "my_dob": "",
        "my_tob": "",
        "my_pob": "",
        "my_gotra": "",
        "my_height": "",
        "my_education": "",
        "my_occupation": "",
        "my_city": "Delhi NCR",
        "my_family_summary": "Brother: Saurabh Jha (Software Engineer at Zscaler)",
        "shareable_whatsapp_bio": (
            "Namaste! Sharing my sister's profile & biodata details:\n"
            "• Name: [Sister's Name]\n"
            "• Education & Profession: [Details]\n"
            "• Location: Delhi NCR\n"
            "• Family: Brother — Saurabh Jha (Software Engineer at Zscaler)\n"
            "Please let us know once you have had a chance to review, and we would be happy to share her full biodata PDF & birth details for Kundli."
        ),
    },
    "alert_devices": {
        "phone_1_name": "Saurabh's Phone",
        "phone_1_whatsapp": "",
        "phone_1_email": "",
        "phone_1_ntfy_topic": "",
        "phone_2_name": "Mummy / Sister's Phone",
        "phone_2_whatsapp": "",
        "phone_2_email": "",
        "phone_2_ntfy_topic": "",
        "default_reminder_minutes_before": 30,
    },
}


COLUMN_MIGRATIONS = {
    "profiles": {
        "external_platform": "TEXT",
        "external_profile_id": "TEXT",
        "external_profile_url": "TEXT",
    },
    "interactions": {
        "ai_applied_at": "TEXT",
        "has_voice": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, columns in COLUMN_MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, col_type in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL CHECK(role IN ('owner', 'family')),
            avatar_color TEXT NOT NULL DEFAULT 'terracotta',
            pin_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            gender TEXT DEFAULT 'Female',
            dob TEXT,
            age INTEGER,
            time_of_birth TEXT,
            place_of_birth TEXT,
            height TEXT,
            marital_status TEXT DEFAULT 'Never Married',
            diet TEXT,
            smoking_drinking TEXT,
            avatar_url TEXT,
            disambiguation_tag TEXT,

            education TEXT,
            college TEXT,
            occupation TEXT,
            company TEXT,
            annual_ctc TEXT,
            work_mode TEXT,
            current_city TEXT,
            hometown TEXT,
            relocation_openness TEXT,

            father_details TEXT,
            mother_details TEXT,
            siblings_details TEXT,
            family_type TEXT,
            family_location TEXT,
            caste_community TEXT,
            sub_caste TEXT,
            gotra TEXT,
            manglik TEXT DEFAULT 'Unknown',
            kundli_status TEXT DEFAULT 'Not Checked',
            kundli_gunas TEXT,
            kundli_notes TEXT,
            gotra_clash_alert TEXT,

            source_channel TEXT DEFAULT 'Relative',
            source_name TEXT,
            source_phone TEXT,
            primary_contact_name TEXT,
            primary_contact_relation TEXT,
            primary_contact_phone TEXT,
            candidate_phone TEXT,
            linkedin_or_social TEXT,

            status TEXT NOT NULL DEFAULT 'New',
            ball_in_court TEXT NOT NULL DEFAULT 'us',
            pass_reason TEXT,
            snooze_until TEXT,
            priority TEXT NOT NULL DEFAULT 'Normal',

            our_biodata_sent INTEGER NOT NULL DEFAULT 0,
            our_photos_sent INTEGER NOT NULL DEFAULT 0,
            our_kundli_sent INTEGER NOT NULL DEFAULT 0,
            numbers_exchanged INTEGER NOT NULL DEFAULT 0,

            ai_fit_score INTEGER,
            fit_summary TEXT,
            positives_json TEXT NOT NULL DEFAULT '[]',
            concerns_json TEXT NOT NULL DEFAULT '[]',
            missing_questions_json TEXT NOT NULL DEFAULT '[]',
            pre_call_brief TEXT,
            shared_family_notes TEXT,
            private_notes TEXT,
            embedding_json TEXT,

            created_by_member TEXT NOT NULL DEFAULT 'Saurabh',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
            import_job_id INTEGER,
            asset_type TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            url_path TEXT NOT NULL,
            mime_type TEXT,
            transcript_or_ocr TEXT,
            uploaded_by TEXT NOT NULL DEFAULT 'Saurabh',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            interaction_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            raw_text TEXT,
            transcript TEXT,
            visibility TEXT NOT NULL DEFAULT 'shared' CHECK(visibility IN ('shared', 'owner_only')),
            created_by_member TEXT NOT NULL DEFAULT 'Saurabh',
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS family_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            member_name TEXT NOT NULL,
            member_role TEXT NOT NULL,
            vote TEXT NOT NULL CHECK(vote IN ('shortlist', 'discuss', 'pass')),
            comment TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(profile_id, member_name)
        );

        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            task TEXT NOT NULL,
            due_date TEXT,
            assigned_to TEXT DEFAULT 'Family',
            ball_in_court TEXT DEFAULT 'us',
            completed INTEGER NOT NULL DEFAULT 0,
            created_by_member TEXT NOT NULL DEFAULT 'Saurabh',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL DEFAULT 'single',
            target_profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'pending_review',
            source_name TEXT,
            source_channel TEXT,
            raw_text TEXT,
            voice_transcript TEXT,
            extracted_json TEXT NOT NULL DEFAULT '{}',
            created_by_member TEXT NOT NULL DEFAULT 'Saurabh',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            settings_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            relation TEXT NOT NULL DEFAULT 'Relative',
            side TEXT NOT NULL DEFAULT 'Maternal',
            phone TEXT,
            city TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            stage TEXT NOT NULL DEFAULT 'proposing' CHECK(stage IN ('proposing', 'scheduled', 'completed', 'cancelled')),
            meeting_type TEXT NOT NULL DEFAULT 'Family Phone Call',
            title TEXT NOT NULL,
            proposed_slots_text TEXT,
            scheduled_at TEXT,
            location_or_link TEXT,
            participants TEXT DEFAULT 'Saurabh, Mummy & Prospect Family',
            pre_meeting_notes TEXT,
            reminder_minutes INTEGER NOT NULL DEFAULT 30,
            notify_phone_1 INTEGER NOT NULL DEFAULT 1,
            notify_phone_2 INTEGER NOT NULL DEFAULT 1,
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            post_meeting_notes TEXT,
            call_recording_url TEXT,
            call_transcript TEXT,
            ai_call_summary TEXT,
            created_by_member TEXT NOT NULL DEFAULT 'Saurabh',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS worker_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            last_heartbeat_at TEXT NOT NULL,
            worker_hostname TEXT,
            worker_mode TEXT DEFAULT 'outbound_poller'
        );

        CREATE TABLE IF NOT EXISTS worker_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS instance_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    _ensure_columns(conn)
    cur.execute("INSERT OR IGNORE INTO instance_meta (key, value) VALUES ('data_epoch', ?)", (uuid.uuid4().hex,))

    now = utc_now()
    # Ensure Father / Papa is removed from login members per user request
    cur.execute("DELETE FROM members WHERE lower(name) IN ('papa', 'father')")

    existing_members = cur.execute("SELECT COUNT(*) as c FROM members").fetchone()["c"]
    if existing_members == 0:
        cur.executemany(
            "INSERT INTO members (name, role, avatar_color, pin_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("Saurabh", "owner", "terracotta", hash_pin(OWNER_DEFAULT_PIN), now),
                ("Mummy", "family", "sage", hash_pin(FAMILY_DEFAULT_PIN), now),
                ("Sister", "family", "indigo", hash_pin(FAMILY_DEFAULT_PIN), now),
            ],
        )
    else:
        has_sister = cur.execute("SELECT COUNT(*) as c FROM members WHERE lower(name) = 'sister'").fetchone()["c"]
        if has_sister == 0:
            cur.execute(
                "INSERT INTO members (name, role, avatar_color, pin_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                ("Sister", "family", "indigo", hash_pin(FAMILY_DEFAULT_PIN), now),
            )

    # Backfill relatives table from any existing profile source_name
    distinct_sources = cur.execute(
        "SELECT DISTINCT source_name, source_channel, source_phone FROM profiles WHERE source_name IS NOT NULL AND trim(source_name) != ''"
    ).fetchall()
    for src in distinct_sources:
        cur.execute(
            """
            INSERT OR IGNORE INTO relatives (name, relation, side, phone, city, notes, created_at, updated_at)
            VALUES (?, ?, 'Family', ?, '', 'Auto-imported from profile source', ?, ?)
            """,
            (src["source_name"].strip(), src["source_channel"] or "Relative", src["source_phone"] or "", now, now),
        )

    existing_settings = cur.execute("SELECT COUNT(*) as c FROM app_settings WHERE id = 1").fetchone()["c"]
    if existing_settings == 0:
        cur.execute(
            "INSERT INTO app_settings (id, settings_json, updated_at) VALUES (1, ?, ?)",
            (json.dumps(DEFAULT_SETTINGS), now),
        )

    conn.commit()
    conn.close()


def get_app_settings() -> dict:
    conn = get_conn()
    row = conn.execute("SELECT settings_json FROM app_settings WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(row["settings_json"])
        merged = dict(DEFAULT_SETTINGS)
        merged.update(stored)
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def update_app_settings(new_settings: dict) -> dict:
    current = get_app_settings()
    for k, v in new_settings.items():
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            current[k] = {**current[k], **v}
        else:
            current[k] = v
    conn = get_conn()
    conn.execute(
        "UPDATE app_settings SET settings_json = ?, updated_at = ? WHERE id = 1",
        (json.dumps(current), utc_now()),
    )
    conn.commit()
    conn.close()
    return current


USER_DATA_TABLES = (
    "profiles",
    "import_jobs",
    "relatives",
    "interactions",
    "meetings",
    "family_votes",
    "follow_ups",
    "media_assets",
)
VOLATILE_TABLES = ("worker_state", "worker_tasks")


def get_data_epoch() -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM instance_meta WHERE key = 'data_epoch'").fetchone()
    conn.close()
    return row["value"] if row else ""


def count_user_rows() -> int:
    conn = get_conn()
    total = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in USER_DATA_TABLES)
    conn.close()
    return total


def _dump_line_table(line: str) -> str | None:
    for prefix in ("INSERT INTO ", "CREATE TABLE ", "CREATE INDEX "):
        if line.startswith(prefix):
            rest = line[len(prefix):].lstrip()
            if rest.startswith('"'):
                return rest[1:].split('"', 1)[0]
            return rest.split(None, 1)[0].split("(")[0]
    return None


def logical_sha() -> str:
    conn = get_conn()
    h = hashlib.sha256()
    for line in conn.iterdump():
        tbl = _dump_line_table(line)
        if tbl in VOLATILE_TABLES:
            continue
        if tbl == "sqlite_sequence" and any(f"'{t}'" in line for t in VOLATILE_TABLES):
            continue
        h.update(line.encode("utf-8", "replace"))
        h.update(b"\n")
    conn.close()
    return h.hexdigest()


def sqlite_backup_to(dest: Path) -> None:
    src = get_conn()
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def create_sqlite_backup() -> Path:
    backup_dir = MEDIA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"rishta_backup_{stamp}.sqlite"
    if DB_PATH.exists():
        sqlite_backup_to(dest)
    return dest
