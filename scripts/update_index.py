#!/usr/bin/env python3
"""Add new techai Naver Blog posts to the existing GitHub Pages index."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote_plus, urlencode
from zoneinfo import ZoneInfo


BLOG_ID = "techai"
BASE_URL = "https://techai-n.github.io/techai-google-index/"
FEED_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
ARCHIVE_URL = "https://blog.naver.com/PostTitleListAsync.naver"
ROOT = Path(__file__).resolve().parents[1]
POST_ID_RE = re.compile(r"/(\d{10,})")
TAG_RE = re.compile(r"<[^>]+>")
CATEGORIES = {
    "1": "AI", "6": "Tech", "7": "애플", "8": "삼성", "9": "LLM",
    "11": "자동차", "12": "IT", "13": "통신", "14": "정보",
    "15": "구글", "17": "제품", "18": "생활", "19": "정보", "20": "게임",
}


@dataclass(frozen=True)
class Post:
    log_no: str
    title: str
    category: str
    published: str
    summary: str

    @property
    def source_url(self) -> str:
        return f"https://m.blog.naver.com/{BLOG_ID}/{self.log_no}"

    @property
    def page_url(self) -> str:
        return f"{BASE_URL}posts/{self.log_no}/"


def clean_text(value: str) -> str:
    value = TAG_RE.sub(" ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def shorten(value: str, limit: int = 240) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "techai-google-index/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not fetch {url}")


def parse_feed(payload: bytes) -> list[Post]:
    root = ET.fromstring(payload)
    posts: list[Post] = []
    for item in root.findall("./channel/item"):
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        match = POST_ID_RE.search(guid)
        if not match:
            continue
        title = clean_text(item.findtext("title") or "")
        summary = clean_text(item.findtext("description") or "")
        if summary.startswith(title):
            summary = summary[len(title) :].strip()
        published = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        posts.append(Post(
            log_no=match.group(1),
            title=title,
            category=clean_text(item.findtext("category") or "기타") or "기타",
            published=published,
            summary=shorten(summary) or f"{title}에 관한 techai 네이버 블로그 포스팅입니다.",
        ))
    return sorted(posts, key=lambda post: (post.published, post.log_no), reverse=True)


def parse_archive_page(payload: bytes) -> dict:
    # Naver's pagingHtml contains invalid JSON escapes such as \'. The post
    # records themselves are valid after removing that unnecessary escape.
    return json.loads(payload.decode("utf-8").replace("\\'", "'"))


def archive_date(value: str, recent: dict[str, Post], log_no: str) -> str:
    match = re.fullmatch(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", value.strip())
    if match:
        year, month, day = map(int, match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    if log_no in recent:
        return recent[log_no].published
    raise RuntimeError(f"Archive returned a relative date for non-RSS post {log_no}: {value}")


def load_archive(recent_posts: list[Post]) -> list[Post]:
    recent = {post.log_no: post for post in recent_posts}
    archive: dict[str, Post] = {}
    expected_total = None
    page = 1
    while expected_total is None or len(archive) < expected_total:
        query = urlencode({
            "blogId": BLOG_ID, "viewdate": "", "currentPage": page,
            "categoryNo": 0, "parentCategoryNo": "", "countPerPage": 30,
        })
        data = parse_archive_page(read_url(f"{ARCHIVE_URL}?{query}"))
        if data.get("resultCode") != "S":
            raise RuntimeError(f"Naver archive request failed on page {page}")
        expected_total = int(data["totalCount"])
        records = data.get("postList", [])
        if not records:
            break
        for record in records:
            log_no = str(record["logNo"])
            if log_no in recent:
                archive[log_no] = recent[log_no]
                continue
            title = clean_text(unquote_plus(record.get("title", "")))
            archive[log_no] = Post(
                log_no=log_no,
                title=title,
                category=CATEGORIES.get(str(record.get("categoryNo", "")), "기타"),
                published=archive_date(record.get("addDate", ""), recent, log_no),
                summary=f"{title}에 관한 techai 네이버 블로그 포스팅입니다.",
            )
        page += 1
        if page > 100:
            raise RuntimeError("Naver archive exceeded the 100-page safety limit")
    if expected_total is None or len(archive) != expected_total:
        raise RuntimeError(f"Incomplete Naver archive: expected {expected_total}, received {len(archive)}")
    # The API already returns the blog's authoritative newest-first order.
    # Preserve it instead of guessing within-day order from dates or log IDs.
    return list(archive.values())


def keywords(post: Post) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9.+-]*", post.title)
    ignored = {"정리", "방법", "공개", "출시", "사용", "이유", "후기", "리뷰"}
    result = [post.category, "techai", "네이버 블로그"]
    for word in words:
        if len(word) >= 2 and word not in ignored and word not in result:
            result.append(word)
        if len(result) == 9:
            break
    return result


def display_date(value: str) -> str:
    date = datetime.strptime(value, "%Y-%m-%d")
    return f"{date.year}. {date.month}. {date.day}."


def render_post(post: Post, newer: Post | None, older: Post | None, updated: str) -> str:
    title = html.escape(post.title)
    summary = html.escape(post.summary, quote=True)
    category = html.escape(post.category)
    keyword_values = keywords(post)
    nav = []
    if newer:
        nav.append(f'<a href="../{newer.log_no}/">최신 글</a>')
    if older:
        nav.append(f'<a href="../{older.log_no}/">이전 글</a>')
    schema = {
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": post.title, "url": post.page_url, "mainEntityOfPage": post.page_url,
        "isBasedOn": post.source_url, "datePublished": post.published, "dateModified": updated,
        "author": {"@type": "Person", "name": BLOG_ID},
        "publisher": {"@type": "Organization", "name": BLOG_ID},
        "articleSection": post.category, "description": post.summary, "keywords": keyword_values,
    }
    return f'''<!doctype html>
<html lang="ko"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | techai 네이버 블로그</title>
  <meta name="description" content="{summary}"><meta name="keywords" content="{html.escape(', '.join(keyword_values), quote=True)}">
  <meta name="robots" content="index, follow"><link rel="canonical" href="{post.page_url}">
  <meta property="og:title" content="{title}"><meta property="og:description" content="{summary}"><meta property="og:type" content="article"><meta property="og:url" content="{post.page_url}">
  <script type="application/ld+json">{json.dumps(schema, ensure_ascii=False, indent=2)}</script>
  <style>
    :root {{ color-scheme:light; --ink:#1b2430; --muted:#556070; --line:#dce4ef; --brand:#176b87; --accent:#c94f2d; --paper:#fff; --soft:#f5f8fb; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--soft); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.65; }}
    main {{ width:min(860px,calc(100% - 32px)); margin:auto; padding:56px 0 64px; }} .eyebrow {{ color:var(--accent); font-size:14px; font-weight:700; margin:0 0 8px; }}
    h1 {{ font-size:clamp(30px,7vw,48px); line-height:1.15; margin:0 0 16px; }} p {{ margin:0 0 16px; }} .lead {{ color:var(--muted); font-size:18px; }}
    .panel {{ background:var(--paper); border:1px solid var(--line); border-radius:8px; padding:24px; margin-top:24px; }} h2 {{ font-size:22px; margin:0 0 14px; }}
    .keyword-list,.meta,.nav {{ display:flex; flex-wrap:wrap; gap:8px; }} .keyword-list span {{ border:1px solid var(--line); border-radius:999px; color:var(--muted); font-size:14px; padding:5px 10px; }}
    .meta {{ color:var(--muted); font-size:14px; margin-bottom:16px; }} .button {{ display:inline-flex; min-height:44px; align-items:center; padding:10px 16px; border-radius:6px; background:var(--brand); color:#fff; font-weight:700; text-decoration:none; }}
    .nav {{ margin-top:24px; }} .nav a,.text-link {{ color:var(--brand); font-weight:700; text-underline-offset:3px; }} footer {{ border-top:1px solid var(--line); color:var(--muted); font-size:14px; margin-top:32px; padding-top:20px; }}
  </style>
</head><body><main>
  <p class="eyebrow">TECHAI NAVER BLOG POST</p><h1>{title}</h1>
  <div class="meta"><span>{category}</span><time datetime="{post.published}">{display_date(post.published)}</time><span>techai</span></div><p class="lead">{summary}</p>
  <section class="panel" aria-labelledby="keywords"><h2 id="keywords">핵심 키워드</h2><div class="keyword-list">{''.join(f'<span>{html.escape(word)}</span>' for word in keyword_values)}</div></section>
  <section class="panel" aria-labelledby="original"><h2 id="original">네이버 원문</h2><p>전체 본문과 이미지는 techai 네이버 블로그 원문에서 확인할 수 있습니다.</p><p><a class="button" href="{post.source_url}" rel="noopener">네이버 블로그 원문 보기</a></p><p><a class="text-link" href="../../">전체 포스팅 목록으로 돌아가기</a></p></section>
  <nav class="nav" aria-label="post navigation">{' '.join(nav)}</nav>
  <footer><p>Published: {post.published}</p><p>Last updated: {updated}</p><p>Original URL: <a class="text-link" href="{post.source_url}" rel="noopener">{post.source_url}</a></p></footer>
</main></body></html>
'''


def render_card(post: Post, position: int) -> str:
    return f'''      <article class="post-card">
        <div class="post-meta">
          <span>{position:03d}</span>
          <span>{html.escape(post.category)}</span>
          <time datetime="{post.published}">{display_date(post.published)}</time>
        </div>
        <h3><a href="posts/{post.log_no}/">{html.escape(post.title)}</a></h3>
        <p class="card-summary">{html.escape(post.summary)}</p>
        <p><a class="source-link" href="{post.source_url}" rel="noopener">네이버 원문 보기</a></p>
      </article>
'''


def index_post_ids(document: str) -> list[str]:
    return re.findall(r'<h3><a href="posts/(\d+)/">', document)


def update_index(document: str, posts: list[Post], updated: str) -> str:
    card_pattern = re.compile(r'      <article class="post-card">.*?      </article>\n', re.DOTALL)
    cards: dict[str, str] = {}
    for card in card_pattern.findall(document):
        match = re.search(r'<h3><a href="posts/(\d+)/">', card)
        if match:
            cards[match.group(1)] = card

    ordered_cards = []
    for position, post in enumerate(posts, 1):
        card = cards.get(post.log_no, render_card(post, position))
        card = re.sub(
            r'(<div class="post-meta">\s*<span>)\d+(</span>)',
            rf'\g<1>{position:03d}\g<2>', card, count=1,
        )
        ordered_cards.append(card)
    document, replacements = re.subn(
        r'(      <div class="post-grid">\n).*?(      </div>\n    </section>)',
        lambda match: match.group(1) + "".join(ordered_cards) + match.group(2),
        document, count=1, flags=re.DOTALL,
    )
    if replacements != 1:
        raise RuntimeError("Could not replace the post grid in index.html")

    json_items = "\n".join(
        "        " + json.dumps(
            {"@type": "ListItem", "position": position, "name": post.title, "url": post.page_url},
            ensure_ascii=False,
        ) + ("," if position < len(posts) else "")
        for position, post in enumerate(posts, 1)
    )
    document, replacements = re.subn(
        r'(      "itemListElement": \[\n).*?(\n      \])',
        lambda match: match.group(1) + json_items + match.group(2),
        document, count=1, flags=re.DOTALL,
    )
    if replacements != 1:
        raise RuntimeError("Could not replace ItemList JSON-LD in index.html")

    total = len(posts)
    document = re.sub(r'("numberOfItems":\s*)\d+', rf'\g<1>{total}', document, count=1)
    document = re.sub(r'(전체 공개 포스팅 )\d+(개)', rf'\g<1>{total}\g<2>', document, count=1)
    document = re.sub(r'(<div class="stat"><strong>)\d+(</strong><span>전체 공개 포스팅)', rf'\g<1>{total}\g<2>', document, count=1)
    document = re.sub(r'(<div class="stat"><strong>)[^<]+(</strong><span>목록 갱신일)', rf'\g<1>{display_date(updated)}\g<2>', document, count=1)
    document = re.sub(r'(Last updated:\s*)\d{4}-\d{2}-\d{2}', rf'\g<1>{updated}', document, count=1)
    return document


def render_sitemap(posts: list[Post], updated: str) -> str:
    entries = "".join(f'''  <url>
    <loc>{post.page_url}</loc>
    <lastmod>{post.published}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
''' for post in posts)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}</loc>
    <lastmod>{updated}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
{entries}</urlset>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-file", type=Path, help="Read RSS XML from a local file")
    parser.add_argument("--check", action="store_true", help="Validate the feed without writing files")
    args = parser.parse_args()
    payload = args.feed_file.read_bytes() if args.feed_file else read_url(FEED_URL)
    feed_posts = parse_feed(payload)
    if not feed_posts:
        raise RuntimeError("Naver RSS returned no usable posts; refusing to change the site")
    archive_posts = load_archive(feed_posts)

    post_root = ROOT / "posts"
    existing_ids = {path.name for path in post_root.iterdir() if path.is_dir() and (path / "index.html").is_file()}
    new_posts = [post for post in archive_posts if post.log_no not in existing_ids]
    index_path = ROOT / "index.html"
    index_document = index_path.read_text(encoding="utf-8")
    expected_order = [post.log_no for post in archive_posts]
    order_changed = index_post_ids(index_document) != expected_order
    print(f"RSS posts: {len(feed_posts)}, archive posts: {len(archive_posts)}, existing posts: {len(existing_ids)}, new posts: {len(new_posts)}, reorder needed: {order_changed}")
    if args.check or (not new_posts and not order_changed):
        return 0

    updated = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    archive_positions = {post.log_no: position for position, post in enumerate(archive_posts)}
    for post in new_posts:
        position = archive_positions[post.log_no]
        path = post_root / post.log_no / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_post(post, archive_posts[position - 1] if position else None, archive_posts[position + 1] if position + 1 < len(archive_posts) else None, updated), encoding="utf-8")

    sitemap_path = ROOT / "sitemap.xml"
    index_path.write_text(update_index(index_document, archive_posts, updated), encoding="utf-8")
    sitemap_path.write_text(render_sitemap(archive_posts, updated), encoding="utf-8")
    print(f"Updated {len(archive_posts)} indexed posts ({len(new_posts)} newly created).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"update failed: {error}", file=sys.stderr)
        raise
