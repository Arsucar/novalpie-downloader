import sys
from urllib.parse import urlparse
from typing import Any
import requests
from bs4 import BeautifulSoup, Tag

from . import config
from . import utils

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

def make_session(cookie_line: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(config.DEFAULT_HEADERS)
    if cookie_line:
        s.headers["Cookie"] = cookie_line
        for k, v in utils.parse_cookie_line(cookie_line).items():
            s.cookies.set(k, v, domain=urlparse(config.base_url).hostname)
    return s

def parse_book_url(chapter_url: str) -> tuple[int, int]:
    parsed = urlparse(chapter_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3 or parts[-3] != "book":
        raise ValueError(f"Invalid book url: {chapter_url}")
    book_id = int(parts[-2])
    chapter_id = int(parts[-1])
    return book_id, chapter_id

def parse_chapter_items_from_api_payload(payload: Any, book_id: int) -> list[config.ChapterRef]:
    picked_lists: list[list[Any]] = []

    if isinstance(payload, list):
        picked_lists.append(payload)
    elif isinstance(payload, dict):
        for key in ("data", "chapters", "items", "list", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                picked_lists.append(value)
        if not picked_lists:
            for value in payload.values():
                if isinstance(value, list):
                    picked_lists.append(value)

    refs: list[config.ChapterRef] = []
    seen: set[int] = set()
    seq = 0
    for arr in picked_lists:
        for raw in arr:
            if not isinstance(raw, dict):
                continue
            cid = None
            for key in ("id", "chapterId", "chapter_id"):
                cid = utils.extract_int(raw.get(key))
                if cid is not None:
                    break
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = utils.extract_title_from_item(raw) or f"Chapter {seq}"
            order = utils.extract_order_from_item(raw, seq)
            refs.append(
                config.ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=order,
                    url=utils.absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

    if not refs:
        return refs

    sorted_refs = sorted(refs, key=lambda x: (x.index, x.chapter_id))
    changed = any(a.chapter_id != b.chapter_id for a, b in zip(refs, sorted_refs))
    return sorted_refs if changed else refs

def fetch_chapter_list_via_api(session: requests.Session, book_id: int) -> list[config.ChapterRef]:
    api_url = utils.absolute_url(f"/api/novels/{book_id}/chapters")
    resp = session.get(api_url, timeout=(10, config.chapterReadyTimeoutSec))
    resp.raise_for_status()
    payload = resp.json()
    return parse_chapter_items_from_api_payload(payload, book_id)

def extract_chapter_id_from_href(href: str, book_id: int) -> int | None:
    try:
        parts = [p for p in urlparse(href).path.split("/") if p]
        if len(parts) >= 3 and parts[-3] == "book" and int(parts[-2]) == book_id:
            return int(parts[-1])
    except Exception:
        return None
    return None

def fetch_chapter_list_via_html(session: requests.Session, book_id: int, start_url: str) -> list[config.ChapterRef]:
    refs: list[config.ChapterRef] = []
    seen: set[int] = set()
    candidates = [utils.absolute_url(f"/book/{book_id}"), start_url]
    seq = 0
    for u in candidates:
        try:
            r = session.get(u, timeout=(10, config.chapterReadyTimeoutSec))
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")

        for btn in soup.select("[data-chapter-id]"):
            cid = utils.extract_int(btn.get("data-chapter-id"))
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = utils.normalize_text(btn.get_text("\n", strip=True)) or f"Chapter {seq}"
            refs.append(
                config.ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=seq,
                    url=utils.absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

        for a in soup.find_all("a"):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if not href:
                continue
            full = utils.absolute_url(href)
            cid = extract_chapter_id_from_href(full, book_id)
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = utils.normalize_text(a.get_text(" ", strip=True)) or f"Chapter {seq}"
            refs.append(
                config.ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=seq,
                    url=utils.absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

        if refs:
            break
    return refs

def fetch_book_meta(session: requests.Session, book_id: int, chapter_url: str) -> config.BookMeta:
    title = ""
    author = ""
    description = ""
    tags: list[str] = []

    book_url = utils.absolute_url(f"/book/{book_id}")

    if sync_playwright is not None:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=config.headless)
                context = browser.new_context(user_agent=config.DEFAULT_HEADERS["User-Agent"], locale="zh-CN")
                if session.cookies:
                    for cookie in session.cookies:
                        context.add_cookies([{
                            "name": cookie.name,
                            "value": cookie.value,
                            "domain": cookie.domain,
                            "path": cookie.path,
                        }])
                page = context.new_page()
                page.goto(book_url, wait_until="domcontentloaded", timeout=config.pageGotoTimeoutMs)
                page.wait_for_timeout(3000)

                soup = BeautifulSoup(page.content(), "lxml")

                if not title:
                    h1 = soup.select_one("h1")
                    if h1:
                        t = utils.normalize_text(h1.get_text(" ", strip=True))
                        if t:
                            title = t
                if not title:
                    title_tag = soup.find("title")
                    if title_tag:
                        t = utils.normalize_text(title_tag.get_text(" ", strip=True))
                        if t and "-" in t:
                            t = t.split("-")[0].strip()
                            if t:
                                title = t
                if not title:
                    meta = soup.select_one("meta[property='og:title'], meta[name='og:title']")
                    if meta:
                        t = utils.normalize_text(meta.get("content", ""))
                        if t:
                            title = t

                if not description:
                    desc_els = soup.select(".description-content, .description, .summary, #description, .intro, [class*=desc]")
                    for el in desc_els:
                        d = utils.normalize_text(el.get_text(" ", strip=True))
                        if d and len(d) > 20:
                            description = d
                            if not author:
                                author_match = __import__("re").search(r"作者[：:]?\s*([^，。！？]+)", d)
                                if author_match:
                                    author = utils.normalize_text(author_match.group(1))
                            break

                if not description:
                    meta_desc = soup.select_one("meta[property='og:description'], meta[name='description']")
                    if meta_desc:
                        d = utils.normalize_text(meta_desc.get("content", ""))
                        if d:
                            description = d
                            if not author:
                                author_match = __import__("re").search(r"作者[：:]?\s*([^，。！？]+)", d)
                                if author_match:
                                    author = utils.normalize_text(author_match.group(1))

                if not author:
                    meta_author = soup.select_one("meta[property='og:author'], meta[name='author']")
                    if meta_author:
                        a_text = utils.normalize_text(meta_author.get("content", ""))
                        if a_text:
                            author = a_text

                if not author:
                    author_link = soup.select_one("a[href*='author=']")
                    if author_link:
                        a_text = utils.normalize_text(author_link.get_text(" ", strip=True))
                        if a_text:
                            author = a_text

                if not tags:
                    tag_selectors = [
                        ".tags a", ".category a", ".genre a",
                        "a[href*='tag']", "a[href*='category']",
                        ".tag a", ".tags span", ".genre span",
                        ".tag-item"
                    ]
                    for selector in tag_selectors:
                        tag_els = soup.select(selector)
                        for el in tag_els:
                            tag_text = utils.normalize_text(el.get_text(" ", strip=True))
                            if tag_text and len(tag_text) > 1:
                                tags.append(tag_text)
                    tags = utils.unique_keep_order(tags)[:10]

                if description and book_url:
                    description = description + "\n\n来源: " + book_url

                context.close()
                browser.close()
        except Exception as e:
            print(f"[!] Playwright error in fetch_book_meta: {e}", file=sys.stderr)

    if not title:
        candidates = [book_url, chapter_url]
        for u in candidates:
            try:
                r = session.get(u, timeout=(config.chapterReadyTimeoutSec, config.chapterReadyTimeoutSec))
                r.raise_for_status()
            except Exception:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            if not title:
                h1 = soup.select_one("h1")
                if h1:
                    t = utils.normalize_text(h1.get_text(" ", strip=True))
                    if t:
                        title = t
            if not title:
                title_tag = soup.find("title")
                if title_tag:
                    t = utils.normalize_text(title_tag.get_text(" ", strip=True))
                    if t and "-" in t:
                        t = t.split("-")[0].strip()
                        if t:
                            title = t
            if not title:
                meta = soup.select_one("meta[property='og:title'], meta[name='og:title']")
                if meta:
                    t = utils.normalize_text(meta.get("content", ""))
                    if t:
                        title = t
            if not description:
                desc_els = soup.select(".description-content, .description, .summary, #description, .intro, [class*=desc]")
                for el in desc_els:
                    d = utils.normalize_text(el.get_text(" ", strip=True))
                    if d and len(d) > 20:
                        description = d
                        if not author:
                            author_match = __import__("re").search(r"作者[：:]?\s*([^，。！？]+)", d)
                            if author_match:
                                author = utils.normalize_text(author_match.group(1))
                        break
            if not description:
                meta_desc = soup.select_one("meta[property='og:description'], meta[name='description']")
                if meta_desc:
                    d = utils.normalize_text(meta_desc.get("content", ""))
                    if d:
                        description = d
                        if not author:
                            author_match = __import__("re").search(r"作者[：:]?\s*([^，。！？]+)", d)
                            if author_match:
                                author = utils.normalize_text(author_match.group(1))
            if not author:
                meta_author = soup.select_one("meta[property='og:author'], meta[name='author']")
                if meta_author:
                    a_text = utils.normalize_text(meta_author.get("content", ""))
                    if a_text:
                        author = a_text
            if not author:
                author_link = soup.select_one("a[href*='author=']")
                if author_link:
                    a_text = utils.normalize_text(author_link.get_text(" ", strip=True))
                    if a_text:
                        author = a_text
            if not tags:
                tag_selectors = [
                    ".tags a", ".category a", ".genre a",
                    "a[href*='tag']", "a[href*='category']",
                    ".tag a", ".tags span", ".genre span",
                    ".tag-item"
                ]
                for selector in tag_selectors:
                    tag_els = soup.select(selector)
                    for el in tag_els:
                        tag_text = utils.normalize_text(el.get_text(" ", strip=True))
                        if tag_text and len(tag_text) > 1:
                            tags.append(tag_text)
                tags = utils.unique_keep_order(tags)[:10]
            if description and u == book_url:
                description = description + "\n\n来源: " + u

            if title and author and description and tags:
                break

    if not title:
        title = f"book_{book_id}"
    return config.BookMeta(title=title, author=author, description=description, tags=tags)

def download_image_blob(session: requests.Session, url: str) -> tuple[bytes, str, str] | None:
    try:
        resp = session.get(url, timeout=(10, config.chapterReadyTimeoutSec), headers={"Referer": config.base_url})
        resp.raise_for_status()
    except Exception:
        return None

    if not resp.content:
        return None

    content_type = resp.headers.get("Content-Type", "")
    ext = utils.guess_image_extension(url, content_type)
    media_type = utils.guess_image_mime(content_type, ext)
    return resp.content, media_type, ext
