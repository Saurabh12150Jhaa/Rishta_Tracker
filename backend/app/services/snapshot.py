import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .. import db


class SnapshotError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def backup_meta() -> dict:
    return {
        "epoch": db.get_data_epoch(),
        "user_rows": db.count_user_rows(),
        "logical_sha": db.logical_sha(),
    }


def _iter_media_files():
    media_root = db.MEDIA_DIR.resolve()
    backups_root = (db.MEDIA_DIR / "backups").resolve()
    if not media_root.is_dir():
        return
    for path in sorted(media_root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved == backups_root or backups_root in resolved.parents:
            continue
        yield path, path.relative_to(media_root)


def build_snapshot_zip(dest_dir: Path) -> tuple[Path, dict]:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    db_copy = dest_dir / "rishta.sqlite"
    db.sqlite_backup_to(db_copy)
    try:
        manifest = {**backup_meta(), "created_at": db.utc_now()}
        zip_path = dest_dir / "snapshot.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "rishta.sqlite")
            for path, rel in _iter_media_files():
                zf.write(path, f"media/{rel.as_posix()}")
            zf.writestr("manifest.json", json.dumps(manifest))
    finally:
        db_copy.unlink(missing_ok=True)
    return zip_path, manifest


def _validate_media_entry(name: str, media_root: Path) -> Path:
    if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/") or os.path.isabs(name):
        raise SnapshotError(400, f"Unsafe path in backup: {name}")
    target = (media_root.parent / name).resolve()
    if media_root not in target.parents:
        raise SnapshotError(400, f"Unsafe path in backup: {name}")
    return target


def _remap_media_paths(media_root: Path) -> None:
    conn = db.get_conn()
    rows = conn.execute("SELECT id, file_path FROM media_assets").fetchall()
    for r in rows:
        fp = r["file_path"] or ""
        marker = "/media/"
        if marker in fp and not Path(fp).is_file():
            new_path = media_root / fp.rsplit(marker, 1)[1]
            if new_path.is_file():
                conn.execute("UPDATE media_assets SET file_path = ? WHERE id = ?", (str(new_path), r["id"]))
    conn.commit()
    conn.close()


def restore_snapshot_zip(zip_path: Path, force: bool = False) -> dict:
    if db.count_user_rows() > 0 and not force:
        raise SnapshotError(409, "Cloud database already has data; use force=true to overwrite")

    tmp_dir = Path(tempfile.mkdtemp(prefix="rishta_restore_"))
    try:
        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile:
            raise SnapshotError(400, "Not a valid zip file")

        with zf:
            if "rishta.sqlite" not in zf.namelist():
                raise SnapshotError(400, "rishta.sqlite missing from backup")
            media_root = db.MEDIA_DIR.resolve()
            media_entries: list[tuple[str, Path]] = []
            for info in zf.infolist():
                if not info.filename.startswith("media/"):
                    continue
                if info.is_dir():
                    _validate_media_entry(info.filename.rstrip("/"), media_root)
                else:
                    media_entries.append((info.filename, _validate_media_entry(info.filename, media_root)))

            uploaded_db = tmp_dir / "rishta.sqlite"
            with zf.open("rishta.sqlite") as src, open(uploaded_db, "wb") as dst:
                shutil.copyfileobj(src, dst)

            up_conn = None
            try:
                up_conn = sqlite3.connect(str(uploaded_db))
                integrity = up_conn.execute("PRAGMA integrity_check").fetchone()
                has_profiles = up_conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'"
                ).fetchone()
            except sqlite3.DatabaseError:
                if up_conn:
                    up_conn.close()
                raise SnapshotError(400, "Backup database is corrupt")
            if not integrity or integrity[0] != "ok" or not has_profiles:
                up_conn.close()
                raise SnapshotError(400, "Backup database failed integrity check")

            live = db.get_conn()
            try:
                up_conn.backup(live)
            finally:
                up_conn.close()
                live.close()
            db.init_db()

            written = 0
            for name, target in media_entries:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                written += 1

        _remap_media_paths(media_root)
        conn = db.get_conn()
        profiles = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        conn.close()
        return {
            "restored": True,
            "epoch": db.get_data_epoch(),
            "user_rows": db.count_user_rows(),
            "profiles": profiles,
            "media_files": written,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
