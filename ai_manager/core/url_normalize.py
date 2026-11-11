"""URL → comparison key, identical to Link2Note's ``digest/classifier.normalize`` (contract).

Checked against every pair of ``docs/link2note/contract/url_normalize_cases.json``.
youtube:ID / instagram:ID / tiktok:ID; otherwise host/path?query without tracking
parameters, with sorted parameters, without "#…" and a trailing "/"; scheme ignored.
"""
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

YOUTUBE_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
_YT_PATH_PREFIXES = ("shorts", "live", "embed", "v")
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "igsh", "igshid", "si", "ref", "ref_src", "feature"}
_TRACKING_PREFIXES = ("utm_", "share")
_INSTAGRAM_KINDS = {"reel", "reels", "p", "tv"}


def _host(url):
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        host = host.removeprefix(prefix)
    return host


def _on_domain(host, domain):
    return host == domain or host.endswith("." + domain)


def youtube_id(url):
    if _host(url) not in YOUTUBE_HOSTS:
        return None
    u = urlparse(url)
    segments = [s for s in u.path.split("/") if s]
    candidate = ""
    if _host(url) == "youtu.be":
        candidate = segments[0] if segments else ""
    elif segments[:1] == ["watch"]:
        candidate = parse_qs(u.query).get("v", [""])[0]
    elif len(segments) >= 2 and segments[0] in _YT_PATH_PREFIXES:
        candidate = segments[1]
    return candidate if _VIDEO_ID_RE.fullmatch(candidate) else None


def _is_tracking(param):
    p = param.lower()
    return p in _TRACKING_PARAMS or p.startswith(_TRACKING_PREFIXES)


def _platform_key(host, segments):
    if _on_domain(host, "instagram.com"):
        for kind, value in zip(segments, segments[1:]):
            if kind in _INSTAGRAM_KINDS:
                return f"instagram:{value}"
    if _on_domain(host, "tiktok.com") and host != "vm.tiktok.com":
        for kind, value in zip(segments, segments[1:]):
            if kind == "video" and value.isdigit():
                return f"tiktok:{value}"
    return None


def normalize(url):
    url = str(url or "").strip()
    if not url:
        return ""
    if vid := youtube_id(url):
        return f"youtube:{vid}"
    u = urlparse(url)
    host = _host(url)
    segments = [s for s in u.path.split("/") if s]
    if key := _platform_key(host, segments):
        return key
    params = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not _is_tracking(k))
    key = f"{host}{u.path}".rstrip("/")
    return f"{key}?{urlencode(params)}" if params else key
