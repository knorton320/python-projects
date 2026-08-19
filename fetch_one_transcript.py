#!/usr/bin/env python3
"""
Single-episode transcript fetcher (Workflow v2.1, Task 2.2 priority order).

Resolves ONE Apple Podcasts episode and fetches the best available transcript:
    P1  official RSS <podcast:transcript>   -> downloaded here
    P2  YouTube auto-captions               -> printed as a next step
    P4  faster-whisper (large-v3-turbo)     -> printed as a next step (needs audio)

Usage:
    python3 fetch_one_transcript.py "https://podcasts.apple.com/us/podcast/<slug>/id<COLL>?i=<EP>"
"""

import re
import sys
import pathlib
import urllib.parse
import xml.etree.ElementTree as ET

import requests

ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
OUT_DIR = pathlib.Path("podcast_archive/transcripts/_single")  # adjust as needed
UA = "Mozilla/5.0 (PodcastArchiver/2.1)"
TIMEOUT = 60


def parse_input(arg):
    """Return (collection_id, episode_id) from an Apple Podcasts URL."""
    parsed = urllib.parse.urlparse(arg)
    m = re.search(r"/id(\d+)", parsed.path)
    coll = m.group(1) if m else None
    ep = urllib.parse.parse_qs(parsed.query).get("i", [None])[0]
    return coll, ep


def itunes_lookup(**params):
    r = requests.get(ITUNES_LOOKUP, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("results", [])


def resolve_episode(collection_id, episode_id):
    """Find the target episode via the show's episode list (the reliable lookup path)."""
    results = itunes_lookup(id=collection_id, entity="podcastEpisode", limit=200)
    episodes = [x for x in results if x.get("wrapperType") == "podcastEpisode"]
    print(f"  iTunes returned {len(episodes)} episodes for this show")
    ep = next((x for x in episodes if str(x.get("trackId")) == str(episode_id)), None)
    feed_url = results[0].get("feedUrl") if results else None
    return ep, feed_url


def _norm(u):
    return (u or "").split("?")[0].strip().lower()


def find_rss_item(feed_url, guid, enclosure_url, title):
    """Locate the matching <item>: GUID -> enclosure URL -> title (in that order)."""
    r = requests.get(feed_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    channel = ET.fromstring(r.content).find("channel")
    if channel is None:
        return None
    target_guid = (guid or "").strip()
    target_enc = _norm(enclosure_url)
    target_title = (title or "").strip().lower()
    title_match = None
    for item in channel.findall("item"):
        if target_guid and (item.findtext("guid") or "").strip() == target_guid:
            return item
        enc = item.find("enclosure")
        if target_enc and enc is not None and _norm(enc.get("url")) == target_enc:
            return item
        if target_title and (item.findtext("title") or "").strip().lower() == target_title:
            title_match = item
    return title_match


def extract_transcript(item, base_url):
    """Return (url, mimetype) for the best <podcast:transcript>, else None."""
    tags = [el for el in item if el.tag.rsplit("}", 1)[-1] == "transcript"]
    if not tags:
        return None
    priority = {"text/vtt": 0, "application/x-subrip": 1, "text/srt": 1}
    tags.sort(key=lambda t: priority.get((t.get("type") or "").lower(), 9))
    t = tags[0]
    return urllib.parse.urljoin(base_url, t.get("url") or ""), (t.get("type") or "")


def download(url, dest):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return len(r.content)


def sanitize(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:80] or "untitled"


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    coll_id, ep_id = parse_input(sys.argv[1])
    if not (coll_id and ep_id):
        raise SystemExit("Could not read the show id (/id...) and episode id (?i=...) from that URL.")

    print(f"[lookup] show {coll_id} / episode {ep_id}")
    ep, feed_url = resolve_episode(coll_id, ep_id)
    if ep is None:
        raise SystemExit(
            "  Episode not found in the show's most recent 200 episodes.\n"
            "  It may be older than that window, or the ?i= id is wrong.\n"
            f"  Show RSS feed (search it directly): {feed_url}"
        )

    show = ep.get("collectionName", "Unknown_Show")
    title = ep.get("trackName", "")
    date_iso = (ep.get("releaseDate") or "")[:10]
    feed_url = ep.get("feedUrl") or feed_url
    enclosure = ep.get("episodeUrl")
    guid = ep.get("episodeGuid")
    print(f"  show : {show}")
    print(f"  title: {title}")
    print(f"  date : {date_iso}")
    print(f"  feed : {feed_url}")

    print("[P1] scanning RSS for <podcast:transcript> ...")
    item = find_rss_item(feed_url, guid, enclosure, title) if feed_url else None
    if item is not None:
        found = extract_transcript(item, feed_url)
        if found:
            turl, mime = found
            ext = "vtt" if "vtt" in mime.lower() else (
                "srt" if "srt" in mime.lower() or "subrip" in mime.lower() else "txt")
            dest = OUT_DIR / f"{sanitize(show)}_{date_iso}_{sanitize(title)}.{ext}"
            kb = download(turl, dest) / 1024
            print(f"  OFFICIAL transcript found ({mime or 'unknown type'})")
            print(f"  saved -> {dest}  ({kb:.1f} KB)")
            return
        print("  matched the episode, but it has no <podcast:transcript> tag.")
    else:
        print("  could not match this episode inside the RSS feed.")

    print("\n[fallback] No official transcript. Next options (Task 2.2 order):")
    print("  P2  YouTube auto-captions (if this episode is on YouTube):")
    print("        yt-dlp --write-auto-sub --sub-lang en --convert-subs vtt --skip-download <YT_URL>")
    print("  P4  faster-whisper large-v3-turbo on the audio enclosure:")
    print(f"        audio: {enclosure or '(none returned)'}")
    print("        -> feed into your Phase 2 P4 path (transcribe -> normalize -> VTT).")


if __name__ == "__main__":
    main()