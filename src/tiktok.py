"""Core TikTok page/caption logic. No Apify imports here (testable locally).
Never log proxy URLs: callers pass an opaque proxy URL; we never print it."""
from __future__ import annotations
import json, re, time, asyncio
from datetime import datetime, timezone
import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
RX_DATA = re.compile(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
RX_VIDEO = re.compile(r"tiktok\.com/@([^/?#]+)/(video|photo)/(\d{15,22})")
RX_HANDLE = re.compile(r"^(?:https?://(?:www\.|m\.)?tiktok\.com/)?@?([A-Za-z0-9._]{2,24})/?(?:[?#].*)?$")
SHORT_HOSTS = ("vm.tiktok.com", "vt.tiktok.com", "tiktok.com/t/")


class Retryable(Exception):
    """Challenge stub, 429, 5xx, network error -> retry with a new session/IP."""


def new_client(proxy_url: str | None, timeout: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=proxy_url, timeout=timeout, follow_redirects=True, headers=HEADERS)


def parse_handle(s: str) -> str | None:
    s = s.strip()
    m = RX_HANDLE.match(s)
    return m.group(1) if m else None


def parse_video_url(s: str) -> dict | None:
    s = s.strip()
    m = RX_VIDEO.search(s)
    if m:
        return {"handle": m.group(1).lstrip("@"), "kind": m.group(2), "videoId": m.group(3),
                "url": f"https://www.tiktok.com/@{m.group(1).lstrip('@')}/{m.group(2)}/{m.group(3)}"}
    if re.fullmatch(r"\d{15,22}", s):  # bare id
        return {"handle": None, "kind": "video", "videoId": s, "url": f"https://www.tiktok.com/@_/video/{s}"}
    if any(h in s for h in SHORT_HOSTS):
        return {"handle": None, "kind": "short", "videoId": None, "url": s if s.startswith("http") else "https://" + s}
    return None


async def resolve_short(client: httpx.AsyncClient, url: str) -> dict | None:
    r = await client.get(url)
    return parse_video_url(str(r.url))


async def handle_video_ids(client: httpx.AsyncClient, handle: str) -> tuple[list[str], dict]:
    """Recent video ids for a creator via the public embed page (~10 most recent)."""
    r = await client.get(f"https://www.tiktok.com/embed/@{handle}")
    if r.status_code == 429 or r.status_code >= 500:
        raise Retryable(f"embed http {r.status_code}")
    h = r.text
    ids = list(dict.fromkeys(re.findall(r"video/(\d{18,20})", h)))
    fc = re.search(r'"followerCount":(\d+)', h)
    if not ids and len(h) < 5000:
        raise Retryable("embed stub")
    return ids, {"followers": int(fc.group(1)) if fc else None}


async def fetch_item(client: httpx.AsyncClient, url: str) -> tuple[int, dict | None]:
    """Returns (statusCode, itemStruct|None). Raises Retryable on challenge/429."""
    r = await client.get(url)
    if r.status_code == 429 or r.status_code >= 500:
        raise Retryable(f"page http {r.status_code}")
    m = RX_DATA.search(r.text)
    if not m:
        raise Retryable("challenge_or_stub" + (" captcha" if "captcha" in r.text.lower() else ""))
    scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
    vd = scope.get("webapp.video-detail")
    if vd is None:
        raise Retryable("no video-detail scope")
    sc = vd.get("statusCode", -1)
    if sc != 0:
        return sc, None
    return 0, vd["itemInfo"]["itemStruct"]


def caption_tracks(v: dict) -> list[dict]:
    tracks = []
    for s in v.get("subtitleInfos") or []:
        if s.get("Url"):
            tracks.append({"url": s["Url"], "language": s.get("LanguageCodeName") or s.get("LanguageID"),
                           "source": (s.get("Source") or "").upper(), "format": s.get("Format")})
    if not tracks:  # fallback: claInfo.captionInfos
        for c in (v.get("claInfo") or {}).get("captionInfos") or []:
            u = c.get("url") or (c.get("urlList") or [None])[0]
            if u:
                tracks.append({"url": u, "language": c.get("language") or c.get("languageCode"),
                               "source": "ASR" if c.get("isOriginalCaption", True) else "MT", "format": "webvtt"})
    return tracks


ISO1_TO_3 = {"en": "eng", "es": "spa", "fr": "fra", "de": "deu", "pt": "por", "it": "ita", "nl": "nld", "ru": "rus",
             "ar": "ara", "hi": "hin", "id": "ind", "ja": "jpn", "ko": "kor", "zh": "cmn", "th": "tha", "vi": "vie",
             "tr": "tur", "pl": "pol", "uk": "ukr", "ms": "msa", "fil": "fil", "tl": "fil", "bn": "ben", "ur": "urd"}


def lang_matches(code: str | None, wanted: str) -> bool:
    c = (code or "").lower(); w = wanted.lower().strip()
    if not c or not w:
        return False
    if c == w:
        return True
    base_c = c.split("-")[0]; base_w = w.split("-")[0]
    return base_c == ISO1_TO_3.get(base_w, base_w) or base_c == base_w


def pick_track(tracks: list[dict], wanted: str | None, text_lang: str | None = None) -> dict | None:
    """Default: original-language ASR track (subtitleInfos[0] is often an English MT)."""
    if not tracks:
        return None
    if wanted:
        for t in tracks:
            if lang_matches(t["language"], wanted):
                return t
    asr = [t for t in tracks if t["source"] == "ASR"]
    if asr:
        return asr[0]
    if text_lang:  # no ASR label: prefer the track in the post's own language
        for t in tracks:
            if lang_matches(t["language"], text_lang):
                return t
    return tracks[0]


def track_kind(track: dict, tracks: list[dict]) -> str:
    """'original' when TikTok marks it ASR or it is the only track; else 'translation'."""
    return "original" if track["source"] == "ASR" or len(tracks) == 1 else "translation"


def _ts(s: str) -> float:
    p = s.strip().replace(",", ".").split(":")
    p = [float(x) for x in p]
    while len(p) < 3:
        p.insert(0, 0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def parse_vtt(body: str) -> list[dict]:
    segs, cur = [], None
    for line in body.splitlines():
        line = line.strip("\ufeff").rstrip()
        if "-->" in line:
            a, b = line.split("-->")[:2]
            cur = {"start": round(_ts(a), 3), "end": round(_ts(b.split()[0]), 3), "text": ""}
            segs.append(cur)
        elif line and cur is not None and not line.startswith(("WEBVTT", "NOTE")):
            cur["text"] = (cur["text"] + " " + re.sub(r"<[^>]+>", "", line)).strip()
        elif not line:
            cur = None
    return [s for s in segs if s["text"]]


def _fmt(t: float, sep: str) -> str:
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(segs): return "\n".join(f"{i}\n{_fmt(s['start'], ',')} --> {_fmt(s['end'], ',')}\n{s['text']}\n" for i, s in enumerate(segs, 1))
def to_vtt(segs): return "WEBVTT\n\n" + "\n".join(f"{_fmt(s['start'], '.')} --> {_fmt(s['end'], '.')}\n{s['text']}\n" for s in segs)
def seg_text(segs): return " ".join(s["text"] for s in segs).strip()


async def fetch_caption(client: httpx.AsyncClient, track: dict) -> list[dict]:
    r = await client.get(track["url"], headers={"Referer": "https://www.tiktok.com/"})
    if r.status_code == 429 or r.status_code >= 500:
        raise Retryable(f"caption http {r.status_code}")
    if r.status_code != 200:
        raise Retryable(f"caption http {r.status_code}")
    return parse_vtt(r.text)


async def download_media(client: httpx.AsyncClient, v: dict, max_bytes: int = 60_000_000) -> bytes | None:
    u = v.get("playAddr") or v.get("downloadAddr")
    if not u:
        return None
    r = await client.get(u, headers={"Referer": "https://www.tiktok.com/", "Range": "bytes=0-"})
    if r.status_code not in (200, 206):
        raise Retryable(f"media http {r.status_code}")
    return r.content[:max_bytes]


def item_meta(it: dict) -> dict:
    v = it.get("video") or {}; a = it.get("author") or {}; st = it.get("statsV2") or it.get("stats") or {}
    ast = it.get("authorStats") or {}; mu = it.get("music") or {}
    ct = int(it.get("createTime") or 0)
    def n(x):
        try: return int(x)
        except Exception: return None
    return {
        "videoId": it.get("id"),
        "description": it.get("desc"),
        "createTime": datetime.fromtimestamp(ct, timezone.utc).isoformat().replace("+00:00", "Z") if ct else None,
        "durationSecs": v.get("duration"),
        "textLanguage": it.get("textLanguage"),
        "hashtags": [c.get("hashtagName") for c in it.get("textExtra") or [] if c.get("hashtagName")],
        "author": {"handle": a.get("uniqueId"), "nickname": a.get("nickname"), "verified": a.get("verified"),
                   "followers": ast.get("followerCount"), "id": a.get("id")},
        "stats": {"plays": n(st.get("playCount")), "likes": n(st.get("diggCount")), "comments": n(st.get("commentCount")),
                  "shares": n(st.get("shareCount")), "saves": n(st.get("collectCount"))},
        "music": {"title": mu.get("title"), "author": mu.get("authorName"), "original": mu.get("original")},
        "coverUrl": v.get("cover"),
        "isPhotoPost": bool(it.get("imagePost")),
        "isAd": bool(it.get("isAd")),
    }
