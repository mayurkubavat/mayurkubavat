#!/usr/bin/env python3
"""Sync the single latest post from dvhandbook.blogspot.com into README.md."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BLOG_BASE_URL = "https://dvhandbook.blogspot.com"
DEFAULT_FEED_URL = f"{BLOG_BASE_URL}/feeds/posts/default?alt=json&max-results=1"

START_MARKER = "<!-- BLOG-POST-START -->"
END_MARKER = "<!-- BLOG-POST-END -->"

# Matches sites/dvhandbook/data/topics.json hub priority and scripts.js HUB_URLS.
HUB_PRIORITY = [
    ("UVM", f"{BLOG_BASE_URL}/p/uvm.html"),
    ("PCIe", f"{BLOG_BASE_URL}/p/pcie.html"),
    ("SystemVerilog", f"{BLOG_BASE_URL}/p/systemverilog.html"),
    ("Software Engineering", f"{BLOG_BASE_URL}/p/software-engineering.html"),
    ("SystemC", f"{BLOG_BASE_URL}/p/systemc.html"),
    ("Implementation", f"{BLOG_BASE_URL}/p/implementation.html"),
]

ABBREV_RE = re.compile(
    r"\b(?:e\.g|i\.e|etc|vs|cf|approx|Dr|Mr|Ms|Prof|Fig|Eq|Sec|Ch)\.$",
    re.IGNORECASE,
)


class FirstParagraphExtractor(HTMLParser):
    """Extract plain text of the first non-empty <p> element, or full text fallback."""

    SKIP_TAGS = {"script", "style", "figure", "pre", "table", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_p = False
        self._current_p: list[str] = []
        self.paragraphs: list[str] = []
        self._fallback: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and t == "p":
            self._in_p = True
            self._current_p = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth == 0 and t == "p" and self._in_p:
            self._in_p = False
            text = _normalize_ws("".join(self._current_p))
            if text:
                self.paragraphs.append(text)

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_p:
            self._current_p.append(data)
        else:
            self._fallback.append(data)

    def first_text(self) -> str:
        if self.paragraphs:
            return self.paragraphs[0]
        return _normalize_ws("".join(self._fallback))


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def extract_excerpt(html_content: str, max_chars: int = 220) -> str:
    """Return the lead sentence (or word-clamped excerpt) from post HTML."""
    parser = FirstParagraphExtractor()
    parser.feed(html_content or "")
    paragraph = parser.first_text()
    if not paragraph:
        return ""

    # Split at the first true sentence boundary (decimals have no space after '.'; abbreviations are skipped).
    sentence = paragraph
    for match in re.finditer(r"[.!?](?=\s+\S)", paragraph):
        end_idx = match.end()
        prefix = paragraph[:end_idx]
        if not ABBREV_RE.search(prefix):
            sentence = prefix.strip()
            break

    if len(sentence) <= max_chars:
        return sentence

    cut = sentence[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def format_date(iso_str: str) -> str:
    """Format Blogger ISO-8601 timestamp as 'Nov 14, 2026' (no leading zero on day)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def select_primary_label(labels: list[str]) -> tuple[str, str] | None:
    """Pick primary topic label following dvhandbook's hub priority."""
    if not labels:
        return None
    label_set = set(labels)
    for hub_name, hub_url in HUB_PRIORITY:
        if hub_name in label_set:
            return hub_name, hub_url
    first = labels[0]
    encoded = urllib.parse.quote(first, safe="")
    return first, f"{BLOG_BASE_URL}/search/label/{encoded}"


def parse_latest_entry(feed_payload: dict) -> dict[str, str]:
    """Parse the newest entry from Blogger's JSON feed payload."""
    entries = feed_payload.get("feed", {}).get("entry", [])
    if not entries:
        raise ValueError("Blogger feed returned zero post entries")

    entry = entries[0]
    title = _normalize_ws(entry.get("title", {}).get("$t", ""))
    if not title:
        raise ValueError("Latest Blogger entry is missing a title")

    url = ""
    for link in entry.get("link", []):
        if link.get("rel") == "alternate" and link.get("href"):
            url = link["href"].strip()
            break
    if not url:
        raise ValueError("Latest Blogger entry is missing an alternate post URL")

    published_raw = entry.get("published", {}).get("$t", "")
    date_str = format_date(published_raw) if published_raw else ""

    raw_body = (
        entry.get("content", {}).get("$t")
        or entry.get("summary", {}).get("$t")
        or ""
    )
    excerpt = extract_excerpt(raw_body)

    categories = [
        c.get("term", "").strip()
        for c in entry.get("category", [])
        if c.get("term", "").strip()
    ]
    label_info = select_primary_label(categories)

    return {
        "title": title,
        "url": url,
        "date": date_str,
        "excerpt": excerpt,
        "label": label_info[0] if label_info else "",
        "label_url": label_info[1] if label_info else "",
    }


def render_markdown_block(post: dict[str, str]) -> str:
    """Render pure native GitHub Markdown block for the latest post."""
    meta_parts: list[str] = []
    if post.get("date"):
        meta_parts.append(post["date"])
    if post.get("label") and post.get("label_url"):
        meta_parts.append(f'<a href="{html.escape(post["label_url"], quote=True)}">{html.escape(post["label"])}</a>')
    elif post.get("label"):
        meta_parts.append(html.escape(post["label"]))

    lines = [
        START_MARKER,
        f'<sub><strong>LATEST</strong> · <a href="{BLOG_BASE_URL}/">All posts →</a></sub>',
        "",
        f'### [{post["title"]}]({post["url"]})',
    ]
    if post.get("excerpt"):
        lines.extend(["", post["excerpt"]])
    if meta_parts:
        lines.extend(["", f"<sub>{' · '.join(meta_parts)}</sub>"])
    lines.append(END_MARKER)
    return "\n".join(lines)


def update_readme_text(existing_text: str, new_block: str) -> str:
    """Replace content between START_MARKER and END_MARKER, or initialize README."""
    if START_MARKER in existing_text and END_MARKER in existing_text:
        pattern = re.compile(
            re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
            re.DOTALL,
        )
        updated = pattern.sub(lambda _: new_block, existing_text, count=1)
        return updated if updated.endswith("\n") else updated + "\n"
    return new_block + "\n"


def fetch_feed_json(feed_url: str, timeout: int = 20, retries: int = 3) -> dict:
    """Fetch Blogger JSON feed with retry/backoff on transient errors."""
    req = urllib.request.Request(
        feed_url,
        headers={
            "User-Agent": "mayurkubavat-github-profile-sync/1.0",
            "Accept": "application/json",
        },
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch Blogger feed after {retries} attempts: {last_err}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed-url", default=DEFAULT_FEED_URL, help="Blogger JSON feed URL")
    ap.add_argument("--feed-file", type=Path, help="Read feed JSON from a local file instead of network")
    ap.add_argument(
        "--readme",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "README.md",
        help="Path to target README.md",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print generated README without writing")
    args = ap.parse_args(argv)

    if args.feed_file:
        payload = json.loads(args.feed_file.read_text(encoding="utf-8"))
    else:
        payload = fetch_feed_json(args.feed_url)

    post = parse_latest_entry(payload)
    block = render_markdown_block(post)

    existing = args.readme.read_text(encoding="utf-8") if args.readme.exists() else ""
    updated = update_readme_text(existing, block)

    if args.dry_run:
        sys.stdout.write(updated)
        return 0

    if updated != existing:
        args.readme.write_text(updated, encoding="utf-8")
        print(f"Updated {args.readme} -> {post['title']} ({post['date']})")
    else:
        print(f"No change ({post['title']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
