import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

PLATFORM_HOSTS = (
    ("jeevansathi", "Jeevansathi"),
    ("shaadi", "Shaadi"),
    ("bharatmatrimony", "BharatMatrimony"),
)

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]]+", re.I)
_QUERY_ID_KEYS = (
    "username",
    "profilechecksum",
    "profileid",
    "profile_id",
    "matriid",
    "memberid",
    "member_id",
    "userid",
    "user_id",
    "id",
)
_PATH_ID_RE = re.compile(r"^[A-Za-z]{0,5}\d{4,}[A-Za-z0-9]*$|^(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,20}$")
_PATH_SKIP = {"profile", "profiles", "view", "viewprofile", "viewprofile.php", "search", "member", "members", "p"}
_TEXT_ID_RE = re.compile(
    r"(?:profile\s*(?:id|no\.?|number)|js\s*[-_ ]?id|jsid|matri\s*id|member\s*id|user\s*id|username)"
    r"\s*[:#=\-]?\s*([A-Za-z]{0,5}\d{3,}[A-Za-z0-9]*|(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{5,14})",
    re.I,
)


def _platform_for_host(host: str) -> Optional[str]:
    host = host.lower()
    for key, name in PLATFORM_HOSTS:
        if key in host:
            return name
    return None


def _id_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    query = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
    for key in _QUERY_ID_KEYS:
        vals = query.get(key)
        if vals and vals[0].strip():
            return unquote(vals[0].strip())
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    for seg in reversed(segments):
        base = seg.rsplit(".", 1)[0] if seg.lower().endswith((".php", ".html", ".htm")) else seg
        if base.lower() in _PATH_SKIP or seg.lower() in _PATH_SKIP:
            continue
        if _PATH_ID_RE.match(base):
            return base
    return None


def parse_matrimony_reference(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        host = urlparse(url if "://" in url else f"https://{url}").netloc
        platform = _platform_for_host(host)
        if platform:
            full_url = url if "://" in url else f"https://{url}"
            return {"platform": platform, "profile_id": _id_from_url(url), "url": full_url}

    lowered = text.lower()
    platform = None
    for key, name in PLATFORM_HOSTS:
        if key in lowered:
            platform = name
            break
    if platform is None and re.search(r"\bjs\s*[-_ ]?id\b|\bjsid\b", lowered):
        platform = "Jeevansathi"
    if platform is None:
        return None
    id_match = _TEXT_ID_RE.search(text)
    return {"platform": platform, "profile_id": id_match.group(1) if id_match else None, "url": None}


def apply_matrimony_reference(fields: dict, text: Optional[str]) -> Optional[dict]:
    ref = parse_matrimony_reference(text)
    if not ref:
        return None
    fields["external_platform"] = ref["platform"]
    if ref.get("profile_id"):
        fields["external_profile_id"] = ref["profile_id"]
    if ref.get("url"):
        fields["external_profile_url"] = ref["url"]
    if not fields.get("source_channel") or fields.get("source_channel") == "Relative":
        fields["source_channel"] = "Matrimonial App"
    if not fields.get("source_name") or fields.get("source_name") == "WhatsApp Share":
        fields["source_name"] = ref["platform"]
    return ref
