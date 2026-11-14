# TikTok Transcript Scraper: Video to Text, SRT & Captions

**Turn TikTok videos into clean text.** Paste video links or creator handles. For each video you get the **full transcript in the original spoken language**, timed segments, a ready-made **SRT** file, and the video's metadata (description, posting date, duration, hashtags, views, likes, author and follower count).

- 🗣️ **Original language, not a translation.** TikTok often lists an English machine translation first. This Actor picks the creator's own spoken-language captions (Spanish stays Spanish, Portuguese stays Portuguese). You can still ask for a translated track with `captionLanguage`.
- ⚡ **Fast and cheap.** It uses TikTok's own auto-captions: about 0.5–2 seconds per video, with no login, no TikTok account and no residential proxy.
- 🎙️ **Optional Whisper fallback** for videos without TikTok captions. It's off by default, so you never pay for it unless you turn it on.
- 👤 **Creators in, transcripts out.** Give a handle such as `@penniestopounds` and it transcribes their latest videos.
- 🟢 **Fail-safe runs.** Deleted, private and caption-less videos come back as **free status rows** with a `note`. The run still **SUCCEEDS**, so schedules and integrations stay green.
- 💸 **Pay per transcript:** $4 per 1,000 TikTok-caption transcripts. Rows without a transcript are free.

## Quick start (about 20 seconds)
1. Click **Try for free** (or **Start** in Console). The form is prefilled with:
   - two videos: an English career-advice clip and a Portuguese news clip;
   - the creator `@penniestopounds`, with **3 videos** per creator.
2. Click **Start**. In about 10–20 seconds you get **~5 transcripts** with text, SRT, language and video stats, for about **$0.03**.
3. Replace the links with your own videos or creators. Turn on **Whisper fallback** if you also need videos that have no TikTok captions.

## What people use it for
- **Content repurposing:** turn TikToks into blog posts, newsletters, X threads or YouTube Shorts scripts.
- **Subtitles:** download SRT files for re-editing, translation or accessibility.
- **AI and LLM pipelines:** feed transcripts to ChatGPT or Claude for summaries, hooks, topics and sentiment, or build RAG datasets.
- **Creator and competitor research:** what top creators in your niche actually *say*, which hooks they use, and which products they mention.
- **Brand and ad monitoring:** find mentions of your brand in spoken content, not just captions or hashtags.
- **Academic and media research:** quotable, timestamped text from short-form video.
- **Spreadsheets:** send results to Google Sheets with [Google Sheets Export](https://apify.com/latentlark/sheets-export).

## Input
| Field | What it does |
|---|---|
| `videoUrls` | TikTok video links (`https://www.tiktok.com/@user/video/…`), `vm.tiktok.com` / `vt.tiktok.com` short links, or bare video IDs |
| `profiles` | Creator handles or profile URLs (`@user`, `https://www.tiktok.com/@user`) |
| `maxVideosPerProfile` | Recent videos per creator (default 10; TikTok's public embed shows about the latest 10) |
| `captionLanguage` | Empty = original spoken language (recommended). `en`, `eng-US`, `es`… = prefer that translated track if TikTok has it |
| `includeSegments` / `includeSrt` / `includeVtt` | Timed segments (on), SRT (on), WebVTT (off) |
| `whisperFallback` | Off by default. Transcribe videos without TikTok captions with Whisper |
| `whisperModel` | `base` (built in, default), `small` (more accurate, slower) or `tiny` |
| `maxWhisperVideos` / `whisperMaxDurationSecs` | Safety caps for Whisper (default 20 videos, 300 s max length) |
| `proxyMode` | `auto` (default: direct first, Apify Proxy on retry), `none` or `datacenter` |
| `maxConcurrency` | Videos in parallel (default 8) |

**Example input:**
```json
{
  "videoUrls": [
    "https://www.tiktok.com/@careersbychris/video/7696221120462114062",
    "https://www.tiktok.com/@g1/video/7701696635159547154"
  ],
  "profiles": ["@penniestopounds"],
  "maxVideosPerProfile": 3
}
```

**Example with Whisper** (also transcribe videos without captions):
```json
{
  "profiles": ["@yourcompetitor"],
  "maxVideosPerProfile": 10,
  "whisperFallback": true,
  "maxWhisperVideos": 10
}
```

## Output
One row per video. A transcript row looks like this (SRT shortened):
```json
{
  "url": "https://www.tiktok.com/@duolingo/video/7698777733794483469",
  "videoId": "7698777733794483469",
  "status": "ok",
  "transcript": "Papoy llegó con flow y con crocs. No me mires las crocs, traigo pura aura en las crocs…",
  "language": "spa-ES",
  "transcriptSource": "tiktok_captions",
  "captionType": "original",
  "availableCaptions": [{"language": "eng-US", "type": "translation"}, {"language": "spa-ES", "type": "original"}],
  "segments": [{"start": 0.16, "end": 2.4, "text": "Papoy llegó con flow y con crocs."}],
  "srt": "1\n00:00:00,160 --> 00:00:02,400\nPapoy llegó con flow y con crocs.\n…",
  "description": "tengo TOO MUCH flow",
  "createTime": "2026-10-20T15:50:13Z",
  "durationSecs": 10,
  "hashtags": [],
  "author": {"handle": "duolingo", "nickname": "Duolingo", "verified": true, "followers": 18400000},
  "stats": {"plays": 1100000, "likes": 106800, "comments": 3669, "shares": 55700, "saves": 15864},
  "music": {"title": "sonido original", "author": "Pauchisss", "original": true},
  "fetchedVia": "direct",
  "attempts": 1
}
```

**`status` values**
| status | meaning | charged |
|---|---|---|
| `ok` | Transcript returned (`transcriptSource`: `tiktok_captions` or `whisper`) | ✅ |
| `no_captions` | TikTok has no captions for this video (often music-only or no speech). Metadata is still returned | Free |
| `unavailable` | Deleted, private or region-restricted (`tiktokStatusCode`, e.g. 10231) | Free |
| `photo_post` | Photo or slideshow post, nothing to transcribe | Free |
| `invalid_input` / `no_videos` / `error` | Bad link, empty creator, or TikTok kept blocking after 3 attempts | Free |

The **Overview** tab in the dataset shows a compact table. Export to JSON, CSV, Excel or Google Sheets.

## Pricing
Pay per event, with volume discounts on higher Apify plans:

| Event | What it is | Free plan | Bronze | Silver | Gold+ |
|---|---|---|---|---|---|
| `apify-actor-start` | Once per run (per GB of memory; the default 512 MB counts as one start) | $0.005 | $0.005 | $0.005 | $0.005 |
| `transcript` | One video transcript from TikTok's own captions | $0.004 | $0.0036 | $0.0032 | $0.0028 |
| `whisper-transcript` | One video transcript from the Whisper fallback (only when `whisperFallback` is on and speech is found) | $0.015 | $0.0135 | $0.012 | $0.0105 |

- **Free:** `no_captions`, `unavailable`, `photo_post`, `invalid_input`, `no_videos` and `error` rows, plus duplicates. Each video is charged at most once.
- **Examples (Free plan):**
  - The prefilled example (~5 transcripts): about **$0.03**.
  - 1,000 videos with ~65% captioned: about **$2.61**.
  - The same 1,000 videos with Whisper for the rest: about **$7.85**.
- Set **Max cost per run** in Console to cap spend. The Actor stops cleanly when it reaches the limit.

## How it works and limitations
- **Native captions first.** Most talking-head TikToks have TikTok auto-captions. In our tests, about **70% of creator talking-head videos** and about 50% of brand and news videos had them. Music-only clips, memes and some languages have none.
- **The Whisper fallback is optional.** The Actor downloads the video's audio and transcribes it on the Apify server with faster-whisper (base model built in). This takes a few seconds per short video. It's slower than native captions, which is reflected in the higher event price. The default 512 MB works for the built-in `base` model; use 1 GB for `small`.
- **Original vs translation.** `captionType: "original"` is the creator's spoken language. TikTok also offers machine translations for some videos; they're listed in `availableCaptions` and can be requested with `captionLanguage`.
- **Creators:** only the latest ~10 videos per creator are reachable through TikTok's public embed. For older videos, pass their URLs directly.
- **Accuracy** is that of TikTok's auto-captions (or Whisper). Names, brands and slang can be misspelled.
- **Blocks:** about 1–2% of requests get a TikTok challenge page. The Actor retries automatically with a new session through Apify Proxy (up to 3 attempts in total). Our 500-URL tests reached 98–99.7% success at 8 videos in parallel.
- Cover image and video URLs are signed TikTok CDN links that expire after some days.
- Public videos only. No login, no TikTok account, no private data.

## FAQ
**I got 0 transcripts. Why?**
Check the `status` and `note` (or `error`) field of each row:
- `no_captions` means TikTok has no captions for that video. Turn on `whisperFallback` to transcribe it anyway.
- `unavailable` means the video is deleted, private or region-locked.
- `invalid_input` means the link wasn't recognised. Use the full `https://www.tiktok.com/@user/video/<id>` link or a short `vm.tiktok.com` link.
- A creator row with `no_videos` means the account is private or has no public videos.

None of these rows are charged.

**Why is my transcript in Spanish (or another language) and not English?**
By default you get the language actually spoken in the video. If TikTok also has an English translation, set `captionLanguage` to `en`.

**Does it work for YouTube Shorts or Instagram Reels?**
No, this Actor is TikTok-only.

**Can I get more than ~10 videos from a creator?**
TikTok's public embed only lists the latest videos. Collect older video URLs elsewhere and pass them in `videoUrls`.

**Do I need a TikTok account, cookies or residential proxies?**
No.

**How do I get SRT files?**
Each `ok` row has an `srt` field. Export the dataset, or read the field through the API.

## More from LatentLark
- [Facebook Reels Scraper + Transcripts](https://apify.com/latentlark/facebook-reels-scraper): public Facebook Reels with plays, reactions, shares and a spoken-word transcript (captions or Whisper), no login.
- [TikTok Ads Library Scraper](https://apify.com/latentlark/tiktok-ads-library): competitors' TikTok ads from the EU Ad Library and Creative Center Top Ads.
- [Google Sheets Export & Import (No OAuth)](https://apify.com/latentlark/sheets-export): send any dataset to Google Sheets.
- [Telegram Channel Monitor](https://apify.com/latentlark/telegram-channel-monitor): posts from public Telegram channels.
- [Creator Commerce Competitor Finder](https://apify.com/latentlark/creator-commerce-competitor-finder): creators and brands on LTK and ShopMy.
