"""TikTok Transcript (PRIVATE scaffold). Native TikTok captions first; optional Whisper fallback."""
from __future__ import annotations
import asyncio, time
from apify import Actor
from . import tiktok as tt

MAX_ATTEMPTS = 3
# Pay-per-event keys (must match Console pricing / pricing.json)
EV_TRANSCRIPT = "transcript"            # one video transcript from TikTok's own captions
EV_WHISPER = "whisper-transcript"       # one video transcript produced by the Whisper fallback


def can_charge(event: str, n: int = 1) -> bool:
    """False when the user's max-charge-per-run would be exceeded by n more events."""
    try:
        left = Actor.get_charging_manager().calculate_max_event_charge_count_within_limit(event)
    except Exception:
        return True
    return left is None or left >= n


class Ctx:
    def __init__(self, inp, proxy_cfg):
        self.inp = inp; self.proxy_cfg = proxy_cfg
        self.mode = inp.get("proxyMode", "auto")
        self.whisper = bool(inp.get("whisperFallback", False))
        self.whisper_left = int(inp.get("maxWhisperVideos", 20))
        self.whisper_max_dur = int(inp.get("whisperMaxDurationSecs", 300))
        self.counts = {}; self.done = 0; self.total = 0; self.sess = 0
        self.via = {"direct": 0, "proxy": 0}
        self.stopped = False

    def plan(self):
        has_proxy = self.proxy_cfg is not None
        if self.mode == "none" or not has_proxy:
            return ["direct"] * MAX_ATTEMPTS
        if self.mode == "datacenter":
            return ["proxy"] * MAX_ATTEMPTS
        return ["direct"] + ["proxy"] * (MAX_ATTEMPTS - 1)  # auto

    async def client(self, kind):
        if kind == "proxy":
            self.sess += 1
            purl = await self.proxy_cfg.new_url(session_id=f"tt{self.sess % 1000}")
            return tt.new_client(purl)  # purl never logged
        return tt.new_client(None)


async def with_attempts(ctx: Ctx, fn):
    """Run fn(client) with no-proxy-first / proxy-fallback retries. Returns (result, via, attempts, lastErr)."""
    last = None
    for i, kind in enumerate(ctx.plan(), 1):
        try:
            async with await ctx.client(kind) as c:
                return await fn(c), kind, i, None
        except (tt.Retryable, tt.httpx.HTTPError) as e:
            last = f"{type(e).__name__}: {str(e)[:120]}"
            await asyncio.sleep(0.5 * i)
    return None, None, MAX_ATTEMPTS, last


async def process_video(ctx: Ctx, ref: dict, extra: dict):
    inp = ctx.inp
    base = {"inputUrl": ref.get("input"), "url": ref["url"], "videoId": ref.get("videoId"), **extra}
    if ref["kind"] == "photo":
        base.update(status="photo_post", transcript=None)
        return base

    async def work(c):
        r = ref
        if r["kind"] == "short":
            r2 = await tt.resolve_short(c, r["url"])
            if not r2:
                return {"_status": "error", "_err": "could not resolve short link"}
            r = {**r2, "input": ref.get("input")}
            if r["kind"] == "photo":
                return {"_status": "photo_post", "_ref": r}
        sc, it = await tt.fetch_item(c, r["url"])
        if sc != 0:
            return {"_status": "unavailable", "_code": sc, "_ref": r}
        v = it.get("video") or {}
        tracks = tt.caption_tracks(v)
        res = {"_ref": r, "_it": it, "_tracks": tracks}
        if it.get("imagePost"):
            res["_status"] = "photo_post"; return res
        tr = tt.pick_track(tracks, inp.get("captionLanguage"), it.get("textLanguage"))
        if tr:
            segs = await tt.fetch_caption(c, tr)
            res.update(_status="ok" if segs else "no_captions", _segs=segs, _track=tr)
            return res
        res["_status"] = "no_captions"
        dur = v.get("duration") or 0
        if ctx.whisper and dur > ctx.whisper_max_dur:
            res["_whisperSkip"] = f"longer than whisperMaxDurationSecs ({ctx.whisper_max_dur}s)"
        elif ctx.whisper and ctx.whisper_left <= 0:
            res["_whisperSkip"] = "maxWhisperVideos budget used"
        elif ctx.whisper and not can_charge(EV_WHISPER):
            res["_whisperSkip"] = "max charge per run reached"
        if ctx.whisper and ctx.whisper_left > 0 and dur <= ctx.whisper_max_dur and can_charge(EV_WHISPER):
            ctx.whisper_left -= 1
            try:
                data = await tt.download_media(c, v)
                if data:
                    from . import whisper_fallback as wf
                    w = await asyncio.to_thread(wf.transcribe, data, inp.get("whisperModel", "base"), None)
                    if w and w["segments"]:
                        res.update(_status="ok", _segs=w["segments"], _whisper=w)
            except Exception as e:  # keep the native result; never fail the item on fallback
                res["_whisperErr"] = f"{type(e).__name__}: {str(e)[:100]}"
        return res

    t0 = time.time()
    res, via, attempts, err = await with_attempts(ctx, work)
    base.update(fetchedVia=via, attempts=attempts, elapsedMs=int((time.time() - t0) * 1000))
    if res is None:
        base.update(status="error", error=err or "failed", transcript=None)
        return base
    r = res.get("_ref") or ref
    base.update(url=r["url"], videoId=r.get("videoId") or base["videoId"], status=res["_status"])
    if res["_status"] == "unavailable":
        base.update(transcript=None, tiktokStatusCode=res["_code"],
                    note="Video unavailable (deleted, private, or region-restricted)")
        return base
    if res["_status"] == "error":
        base.update(transcript=None, error=res.get("_err")); return base
    it = res.get("_it")
    if it:
        meta = tt.item_meta(it)
        cla = (it.get("video") or {}).get("claInfo") or {}
        base.update(meta)
        base["availableCaptions"] = [{"language": t["language"], "type": tt.track_kind(t, res.get("_tracks") or [])}
                                     for t in res.get("_tracks") or []]
        base["noCaptionReason"] = cla.get("noCaptionReason") if not res.get("_tracks") else None
        if res.get("_whisperErr"): base["whisperError"] = res["_whisperErr"]
    segs = res.get("_segs") or []
    if res["_status"] == "ok":
        if res.get("_whisper"):
            base.update(transcriptSource="whisper", captionType="whisper", language=res["_whisper"]["language"],
                        languageProbability=res["_whisper"]["languageProbability"])
        else:
            tr = res["_track"]
            base.update(transcriptSource="tiktok_captions", captionType=tt.track_kind(tr, res.get("_tracks") or []),
                        language=tr["language"])
        base["transcript"] = tt.seg_text(segs)
        if inp.get("includeSegments", True): base["segments"] = segs
        if inp.get("includeSrt", True): base["srt"] = tt.to_srt(segs)
        if inp.get("includeVtt", False): base["vtt"] = tt.to_vtt(segs)
    else:
        base.setdefault("transcript", None)
        if res["_status"] == "no_captions":
            if not ctx.whisper:
                base["note"] = "No TikTok captions for this video (often music-only or no speech). Not charged. Turn on whisperFallback to transcribe it."
            elif res.get("_whisperSkip"):
                base["note"] = f"No TikTok captions; Whisper skipped: {res['_whisperSkip']}. Not charged."
            else:
                base["note"] = "No TikTok captions and Whisper found no speech. Not charged."
    return base


async def main():
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = [u for u in (inp.get("videoUrls") or []) if isinstance(u, str) and u.strip()]
        # also accept requestListSources-style [{url:..}]
        urls += [u["url"] for u in (inp.get("videoUrls") or []) if isinstance(u, dict) and u.get("url")]
        profiles = [p for p in (inp.get("profiles") or []) if isinstance(p, str) and p.strip()]
        if not urls and not profiles:
            msg = "No input: add at least one TikTok video URL (videoUrls) or creator (profiles)."
            await Actor.push_data({"status": "invalid_input", "transcript": None, "note": msg})  # free status row
            await Actor.set_status_message(msg, is_terminal=True)
            return
        proxy_cfg = None
        if inp.get("proxyMode", "auto") != "none":
            pin = inp.get("proxyConfiguration") or {"useApifyProxy": True}
            try:
                proxy_cfg = await Actor.create_proxy_configuration(actor_proxy_input=pin)
            except Exception as e:
                Actor.log.warning(f"Proxy unavailable, continuing without proxy ({type(e).__name__})")
        ctx = Ctx(inp, proxy_cfg)
        conc = max(1, min(int(inp.get("maxConcurrency", 8)), 16))
        sem = asyncio.Semaphore(conc)

        refs, seen, bad = [], set(), []
        for u in urls:
            r = tt.parse_video_url(u)
            if not r: bad.append(u); continue
            key = r.get("videoId") or r["url"]
            if key in seen: continue
            seen.add(key); refs.append(({**r, "input": u}, {}))
        maxpp = max(1, min(int(inp.get("maxVideosPerProfile", 10)), 30))
        for p in profiles:
            h = tt.parse_handle(p)
            if not h: bad.append(p); continue
            got, via, att, err = await with_attempts(ctx, lambda c, h=h: tt.handle_video_ids(c, h))
            if not got:
                await Actor.push_data({"inputProfile": p, "status": "error", "error": err or "no videos found", "transcript": None})
                continue
            ids, pm = got
            if not ids:
                await Actor.push_data({"inputProfile": p, "status": "no_videos", "transcript": None,
                                       "note": "Profile has no public videos (or is private)"})
            for vid in ids[:maxpp]:
                if vid in seen: continue
                seen.add(vid)
                refs.append(({"handle": h, "kind": "video", "videoId": vid, "url": f"https://www.tiktok.com/@{h}/video/{vid}",
                              "input": p}, {"inputProfile": p}))
        for b in bad:
            await Actor.push_data({"inputUrl": b, "status": "invalid_input", "transcript": None,
                                   "error": "Not a recognised TikTok video URL or handle"})
        ctx.total = len(refs)
        Actor.log.info(f"{len(refs)} videos queued (concurrency {conc}, proxyMode {ctx.mode}, whisper {ctx.whisper})")

        async def one(ref, extra):
            async with sem:
                if ctx.stopped or not can_charge(EV_TRANSCRIPT):
                    ctx.stopped = True
                    return
                try:
                    rec = await process_video(ctx, ref, extra)
                except Exception as e:  # never crash the run on one item
                    rec = {"inputUrl": ref.get("input"), "url": ref["url"], "status": "error", "transcript": None,
                           "error": f"{type(e).__name__}: {str(e)[:150]}"}
                ev = (EV_WHISPER if rec.get("transcriptSource") == "whisper" else EV_TRANSCRIPT) if rec.get("status") == "ok" else None
                if ev:
                    cr = await Actor.push_data(rec, charged_event_name=ev)
                    if getattr(cr, "event_charge_limit_reached", False):
                        ctx.stopped = True
                else:
                    await Actor.push_data(rec)  # status rows are free
                ctx.counts[rec["status"]] = ctx.counts.get(rec["status"], 0) + 1
                if rec.get("fetchedVia"): ctx.via[rec["fetchedVia"]] += 1
                ctx.done += 1
                if ctx.done % 10 == 0 or ctx.done == ctx.total:
                    await Actor.set_status_message(f"{ctx.done}/{ctx.total} videos · " + ", ".join(f"{k} {v}" for k, v in ctx.counts.items()))
        await asyncio.gather(*[one(r, e) for r, e in refs])
        summary = {"videos": ctx.total, "statuses": ctx.counts, "fetchedVia": ctx.via, "invalidInputs": len(bad)}
        await Actor.set_value("OUTPUT", summary)
        ok = ctx.counts.get("ok", 0)
        summary["stoppedAtMaxCharge"] = ctx.stopped
        await Actor.set_value("OUTPUT", summary)
        msg = f"Done: {ok}/{ctx.total} transcripts · " + ", ".join(f"{k} {v}" for k, v in ctx.counts.items())
        if ctx.stopped:
            msg += " · Stopped early: max charge per run reached."
        if ctx.total and not ok:
            msg += " · No transcripts: see the 'note' field of each row (no captions, unavailable or private videos are free)."
        await Actor.set_status_message(msg, is_terminal=True)
