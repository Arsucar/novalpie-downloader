# coding=utf-8
"""
novalpie.cc novel downloader 

How to use:
1) Edit config values in this file (bookURL, maxChapters, etc.).
2) Optional: put cookie string in ./novalpie.txt first line.
3) Run:
   python novalpie.py

Dependencies:
  pip install requests beautifulsoup4 lxml ebooklib playwright
  playwright install chromium
"""

from __future__ import annotations

import html
import hashlib
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from ebooklib import epub

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    PlaywrightTimeoutError = Exception
    sync_playwright = None


# ---------------------------------------------------------------------------
# Config (edit here)
# ---------------------------------------------------------------------------

# bookURL：起始章节链接（必改）
bookURL = "https://novalpie.cc/book/353690/8853740"

# base_url：站点根地址，需与 bookURL 同域名
base_url = "https://novalpie.cc/"

# cookieFilePath：Cookie 文件路径（默认 ./novalpie.txt）
cookieFilePath = "./novalpie.txt"

# headless：是否无头运行浏览器（True/False）
headless = True

# chapterDelayMinSec / chapterDelayMaxSec：章节访问间隔（秒）
chapterDelayMinSec = 2.0
chapterDelayMaxSec = 3.0

# firstChapterExtraWaitSec：首章额外等待时间（秒）
firstChapterExtraWaitSec = 10.0

# chapterReadyTimeoutSec：单章正文等待超时（秒）
chapterReadyTimeoutSec = 35.0

# pageGotoTimeoutMs：页面加载超时（毫秒）
pageGotoTimeoutMs = 130000

# retryPerChapter：单章失败重试次数
retryPerChapter = 4

# maxChapters：最多抓取章节数，0 表示不限制
maxChapters = 0

# startFromCurrentChapter：
#   True  从 bookURL 指向章节开始抓
#   False 从第 1 章开始抓
startFromCurrentChapter = True

# keepFailedChapterPlaceholder：是否保留抓取失败章节占位文本
keepFailedChapterPlaceholder = True

# epubOutputDir / txtOutputDir / cacheOutputDir：输出目录
epubOutputDir = "./epubBooks_novalpie"
txtOutputDir = "./txtBooks_novalpie"
cacheOutputDir = "./cache_novalpie"


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

LOADING_HINTS = ("loading", "加载中", "正在加载")
DROP_LINE_RE = re.compile(
    r"^(上一章|下一章|目录|返回|加载中|正在加载|chapter\s*\d+)$",
    re.IGNORECASE,
)

IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
}

IMAGE_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
}


@dataclass
class ChapterRef:
    chapter_id: int
    title: str
    index: int
    url: str


@dataclass
class ChapterData:
    title: str
    text: str
    url: str
    chapter_id: int
    image_urls: list[str] = field(default_factory=list)


@dataclass
class FailedChapter:
    index: int
    title: str
    url: str
    chapter_id: int
    reason: str


@dataclass
class BookMeta:
    title: str
    author: str

def clean_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", (name or "").strip())
    return name or "novel"


def normalize_text(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_cookie_line(cookie_line: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not cookie_line:
        return result
    for part in cookie_line.split(";"):
        p = part.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            result[k] = v
    return result


def read_cookie_line(path_value: str) -> str:
    p = Path(path_value)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return ""


def make_session(cookie_line: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    if cookie_line:
        s.headers["Cookie"] = cookie_line
        for k, v in parse_cookie_line(cookie_line).items():
            s.cookies.set(k, v, domain=urlparse(base_url).hostname)
    return s


def parse_book_url(chapter_url: str) -> tuple[int, int]:
    parsed = urlparse(chapter_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3 or parts[-3] != "book":
        raise ValueError(f"Invalid book url: {chapter_url}")
    book_id = int(parts[-2])
    chapter_id = int(parts[-1])
    return book_id, chapter_id


def absolute_url(u: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", u)


def is_loading_text(text: str) -> bool:
    t = normalize_text(text).lower()
    if not t:
        return True
    if any(h in t for h in LOADING_HINTS) and len(t) <= 220:
        return True
    return False


def clean_paragraphs(text: str) -> list[str]:
    lines: list[str] = []
    for raw in normalize_text(text).splitlines():
        line = normalize_text(raw)
        if len(line) < 2:
            continue
        if DROP_LINE_RE.match(line):
            continue
        if is_loading_text(line):
            continue
        lines.append(line)
    out: list[str] = []
    prev = None
    for line in lines:
        if line != prev:
            out.append(line)
        prev = line
    return out



COMMENT_SECTION_START_RE = re.compile(r"^章节讨论(?:\s*\(\d+\))?$")
COMMENT_NOISE_RES = [
    re.compile(r"^展开评论$"),
    re.compile(r"^暂无评论.*$"),
    re.compile(r"^\(\d+\)$"),
]


def normalize_title_key(text: str) -> str:
    t = normalize_text(text)
    t = re.sub(r"[\s\"'“”‘’《》〈〉【】\[\]\(\)（）:：,，.!！?？·、\-—_]+", "", t)
    return t.lower()


def extract_chapter_no(text: str) -> int | None:
    t = normalize_text(text)
    m = re.search(r"第\s*(\d+)\s*[章节话卷节]", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:chapter|chap)\s*(\d+)", t, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def build_title_anchors(title: str) -> list[str]:
    t = normalize_text(title)
    if not t:
        return []

    anchors: list[str] = []

    full_key = normalize_title_key(t)
    if len(full_key) >= 2 and not full_key.isdigit():
        anchors.append(full_key)

    no = extract_chapter_no(t)
    if no is not None:
        chapter_cn = normalize_title_key(f"第{no}章")
        chapter_en = normalize_title_key(f"chapter{no}")
        if len(chapter_cn) >= 2 and not chapter_cn.isdigit():
            anchors.append(chapter_cn)
        if len(chapter_en) >= 2 and not chapter_en.isdigit():
            anchors.append(chapter_en)

    subtitle = re.sub(r"^\s*(第\s*\d+\s*[章节话卷节]|(?:chapter|chap)\s*\d+)\s*", "", t, flags=re.IGNORECASE)
    sub_key = normalize_title_key(subtitle)
    if len(sub_key) >= 2 and not sub_key.isdigit():
        anchors.append(sub_key)

    return unique_keep_order(anchors)
def line_matches_anchors(line: str, anchors: list[str]) -> bool:
    if not anchors:
        return False
    key = normalize_title_key(line)
    if not key:
        return False
    for a in anchors:
        if not a:
            continue
        if key == a:
            return True
        if len(a) >= 3 and a in key:
            return True
        if len(key) >= 3 and key in a:
            return True
    return False
def find_title_line_index(lines: list[str], anchors: list[str], start: int = 0) -> int | None:
    if not anchors:
        return None
    for i in range(max(0, start), len(lines)):
        if line_matches_anchors(lines[i], anchors):
            return i
    return None


def is_comment_start_line(line: str) -> bool:
    t = normalize_text(line)
    if not t:
        return False
    if COMMENT_SECTION_START_RE.match(t) is not None:
        return True
    low = t.lower()
    if "章节讨论" in t:
        return True
    if "chapter discussion" in low or low.startswith("comments"):
        return True
    return False
def is_comment_noise_line(line: str) -> bool:
    t = normalize_text(line)
    if not t:
        return True
    for rgx in COMMENT_NOISE_RES:
        if rgx.match(t):
            return True
    low = t.lower()
    if "展开评论" in t or "暂无评论" in t:
        return True
    if low in ("expand comments", "no comments"):
        return True
    return False
def remove_comment_tail(lines: list[str]) -> list[str]:
    for i, line in enumerate(lines):
        if is_comment_start_line(line):
            return lines[:i]

    out = list(lines)
    while out and is_comment_noise_line(out[-1]):
        out.pop()
    return out


def slice_lines_by_title_window(
    lines: list[str],
    current_title: str,
    next_title: str,
    page_title: str,
) -> tuple[list[str], bool]:
    if not lines:
        return [], False

    current_anchors = unique_keep_order(build_title_anchors(current_title) + build_title_anchors(page_title))
    next_anchors = build_title_anchors(next_title)

    if not current_anchors:
        window = remove_comment_tail(lines)
        window = [ln for ln in window if not is_comment_noise_line(ln)]
        return window, True

    start_idx = find_title_line_index(lines, current_anchors, 0)
    if start_idx is None:
        return [], False

    start = start_idx + 1
    end = len(lines)
    next_idx = find_title_line_index(lines, next_anchors, start)
    if next_idx is not None:
        end = next_idx

    window = lines[start:end]

    while window and line_matches_anchors(window[0], current_anchors):
        window = window[1:]

    window = remove_comment_tail(window)
    window = [ln for ln in window if not is_comment_noise_line(ln)]

    if next_anchors:
        window = [ln for ln in window if not line_matches_anchors(ln, next_anchors)]

    return window, True

def extract_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def extract_title_from_item(item: dict[str, Any]) -> str:
    for key in ("title", "chapterTitle", "chapter_title", "name", "chapterName"):
        v = item.get(key)
        if isinstance(v, str) and normalize_text(v):
            return normalize_text(v)
    if isinstance(item.get("chapter"), dict):
        v = item["chapter"].get("title")
        if isinstance(v, str) and normalize_text(v):
            return normalize_text(v)
    return ""


def extract_order_from_item(item: dict[str, Any], default_index: int) -> int:
    for key in ("order", "sort", "seq", "index", "no", "chapterNumber", "chapter_no"):
        n = extract_int(item.get(key))
        if n is not None:
            return n
    return default_index


def parse_chapter_items_from_api_payload(payload: Any, book_id: int) -> list[ChapterRef]:
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

    refs: list[ChapterRef] = []
    seen: set[int] = set()
    seq = 0
    for arr in picked_lists:
        for raw in arr:
            if not isinstance(raw, dict):
                continue
            cid = None
            for key in ("id", "chapterId", "chapter_id"):
                cid = extract_int(raw.get(key))
                if cid is not None:
                    break
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = extract_title_from_item(raw) or f"Chapter {seq}"
            order = extract_order_from_item(raw, seq)
            refs.append(
                ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=order,
                    url=absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

    if not refs:
        return refs

    sorted_refs = sorted(refs, key=lambda x: (x.index, x.chapter_id))
    changed = any(a.chapter_id != b.chapter_id for a, b in zip(refs, sorted_refs))
    return sorted_refs if changed else refs


def fetch_chapter_list_via_api(session: requests.Session, book_id: int) -> list[ChapterRef]:
    api_url = absolute_url(f"/api/novels/{book_id}/chapters")
    resp = session.get(api_url, timeout=(10, chapterReadyTimeoutSec))
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


def fetch_chapter_list_via_html(session: requests.Session, book_id: int, start_url: str) -> list[ChapterRef]:
    refs: list[ChapterRef] = []
    seen: set[int] = set()
    candidates = [absolute_url(f"/book/{book_id}"), start_url]
    seq = 0
    for u in candidates:
        try:
            r = session.get(u, timeout=(10, chapterReadyTimeoutSec))
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")

        for btn in soup.select("[data-chapter-id]"):
            cid = extract_int(btn.get("data-chapter-id"))
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = normalize_text(btn.get_text("\n", strip=True)) or f"Chapter {seq}"
            refs.append(
                ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=seq,
                    url=absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

        for a in soup.find_all("a"):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if not href:
                continue
            full = absolute_url(href)
            cid = extract_chapter_id_from_href(full, book_id)
            if cid is None or cid in seen:
                continue
            seq += 1
            seen.add(cid)
            title = normalize_text(a.get_text(" ", strip=True)) or f"Chapter {seq}"
            refs.append(
                ChapterRef(
                    chapter_id=cid,
                    title=title,
                    index=seq,
                    url=absolute_url(f"/book/{book_id}/{cid}"),
                )
            )

        if refs:
            break
    return refs


def fetch_book_meta(session: requests.Session, book_id: int, chapter_url: str) -> BookMeta:
    title = ""
    author = ""
    candidates = [absolute_url(f"/book/{book_id}"), chapter_url]
    for u in candidates:
        try:
            r = session.get(u, timeout=(chapterReadyTimeoutSec, chapterReadyTimeoutSec))
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        if not title:
            h1 = soup.select_one("h1")
            if h1:
                t = normalize_text(h1.get_text(" ", strip=True))
                if t:
                    title = t
        if not title:
            meta = soup.select_one("meta[property='og:title'], meta[name='og:title']")
            if meta:
                t = normalize_text(meta.get("content", ""))
                if t:
                    title = t
        if not author:
            author_link = soup.select_one("a[href*='author=']")
            if author_link:
                a_text = normalize_text(author_link.get_text(" ", strip=True))
                if a_text:
                    author = a_text
        if title and author:
            break

    if not title:
        title = f"book_{book_id}"
    return BookMeta(title=title, author=author)


def pick_start_index(chapters: list[ChapterRef], start_chapter_id: int, from_current: bool) -> int:
    if not from_current:
        return 0
    for i, ch in enumerate(chapters):
        if ch.chapter_id == start_chapter_id:
            return i
    return 0


def normalize_image_url(url: str, base_page_url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("data:") or u.startswith("blob:"):
        return ""
    if u.startswith("//"):
        u = "https:" + u
    try:
        return urljoin(base_page_url, u)
    except Exception:
        return ""


def unique_image_urls(values: list[str], base_page_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        u = normalize_image_url(raw, base_page_url)
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def chapter_text_from_dom(page, current_title: str = "", next_title: str = "") -> tuple[str, str, list[str], str]:
    payload = page.evaluate(
        r"""(opts) => {
            const norm = (s) => (s || '')
                .replace(/\u00a0/g, ' ')
                .replace(/\r/g, '')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
            const key = (s) => norm(s)
                .toLowerCase()
                .replace(/[\s"'“”‘’《》〈〉【】\[\]\(\)（）:：,，.!！?？·、\-—_]+/g, '');

            const extractNo = (s) => {
                const t = norm(s);
                let m = t.match(/第\s*(\d+)\s*[章节话卷节]/);
                if (m) return parseInt(m[1], 10);
                m = t.match(/(?:chapter|chap)\s*(\d+)/i);
                if (m) return parseInt(m[1], 10);
                return null;
            };

            const unique = (arr) => {
                const out = [];
                const seen = new Set();
                for (const a of arr) {
                    if (!a || seen.has(a)) continue;
                    seen.add(a);
                    out.push(a);
                }
                return out;
            };

            const buildAnchors = (title) => {
                const t = norm(title);
                if (!t) return [];
                const out = [];
                const full = key(t);
                if (full && full.length >= 2 && !/^\d+$/.test(full)) out.push(full);

                const no = extractNo(t);
                if (no !== null) {
                    const c1 = key(`第${no}章`);
                    const c2 = key(`chapter${no}`);
                    if (c1.length >= 2 && !/^\d+$/.test(c1)) out.push(c1);
                    if (c2.length >= 2 && !/^\d+$/.test(c2)) out.push(c2);
                }

                const subtitle = t.replace(/^\s*(第\s*\d+\s*[章节话卷节]|(?:chapter|chap)\s*\d+)\s*/i, '');
                const sub = key(subtitle);
                if (sub.length >= 2 && !/^\d+$/.test(sub)) out.push(sub);
                return unique(out);
            };

            const matchAnchors = (txt, anchors) => {
                if (!anchors || !anchors.length) return false;
                const k = key(txt);
                if (!k) return false;
                for (const a of anchors) {
                    if (!a) continue;
                    if (k === a) return true;
                    if (a.length >= 3 && k.includes(a)) return true;
                    if (k.length >= 3 && a.includes(k)) return true;
                }
                return false;
            };

            const findTitleElement = (root, anchors, afterEl = null) => {
                if (!root || !anchors || !anchors.length) return null;
                const sels = 'h1,h2,h3,h4,h5,h6,p,div,span,strong,b';
                const nodes = root.querySelectorAll(sels);
                for (const el of nodes) {
                    if (afterEl) {
                        const rel = afterEl.compareDocumentPosition(el);
                        if (!(rel & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
                    }
                    const txt = norm(el.innerText || el.textContent || '');
                    if (!txt || txt.length > 120) continue;
                    if (matchAnchors(txt, anchors)) return el;
                }
                return null;
            };

            const imageSig = (img) => {
                return [
                    img.getAttribute('src') || '',
                    img.getAttribute('data-src') || '',
                    img.getAttribute('data-original') || '',
                    img.getAttribute('alt') || '',
                    img.className || '',
                    img.id || ''
                ].join(' ').toLowerCase();
            };

            const inBadContainer = (img, root) => {
                let p = img;
                while (p) {
                    const sig = ((p.className || '') + ' ' + (p.id || '')).toLowerCase();
                    if (/comment|review|reply|avatar|user|profile|toolbar|menu|sidebar|footer|header/.test(sig)) {
                        return true;
                    }
                    if (p === root) break;
                    p = p.parentElement;
                }
                return false;
            };

            const isAfterStart = (node, startEl) => {
                if (!startEl) return true;
                const rel = startEl.compareDocumentPosition(node);
                return !!(rel & Node.DOCUMENT_POSITION_FOLLOWING) || !!(rel & Node.DOCUMENT_POSITION_CONTAINS);
            };

            const isBeforeEnd = (node, endEl) => {
                if (!endEl) return true;
                const rel = endEl.compareDocumentPosition(node);
                return !!(rel & Node.DOCUMENT_POSITION_PRECEDING) || !!(rel & Node.DOCUMENT_POSITION_CONTAINS);
            };

            const collectImages = (root, startEl, endEl) => {
                const urls = [];
                const seen = new Set();
                for (const img of root.querySelectorAll('img')) {
                    if (!isAfterStart(img, startEl) || !isBeforeEnd(img, endEl)) continue;
                    if (inBadContainer(img, root)) continue;

                    const sig = imageSig(img);
                    if (/avatar|icon|emoji|logo|loading|spinner/.test(sig)) continue;

                    let src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original') || '';
                    if (!src) {
                        const srcset = img.getAttribute('srcset') || '';
                        if (srcset) src = srcset.split(',')[0].trim().split(' ')[0].trim();
                    }
                    if (!src || src.startsWith('data:') || src.startsWith('blob:')) continue;

                    let abs = '';
                    try {
                        abs = new URL(src, location.href).href;
                    } catch (_) {
                        continue;
                    }
                    if (!abs || seen.has(abs)) continue;
                    seen.add(abs);
                    urls.push(abs);
                }
                return urls;
            };

            const candidates = [];
            const pushNode = (el, bonus = 0) => {
                if (!el) return;
                const txt = norm(el.innerText || el.textContent || '');
                if (!txt || txt.length < 80) return;
                const cls = ((el.className || '') + ' ' + (el.id || '')).toLowerCase();
                let score = txt.length + bonus;
                if (/chapter|content|reader|read|article|text|novel|正文/.test(cls)) score += 1200;
                if (/comment|footer|header|nav|menu|sidebar|catalog|目录|书评|review|recommend/.test(cls)) score -= 1600;
                candidates.push({ score, text: txt, el });
            };

            const selectors = [
                'article',
                'main',
                '.chapter-content',
                '#chapter-content',
                '.reader-content',
                '.read-content',
                '.prose',
                '[class*=content]',
                '[class*=chapter]',
                '[class*=reader]',
                '[id*=content]',
                '[id*=chapter]'
            ];
            for (const sel of selectors) {
                pushNode(document.querySelector(sel), 600);
            }
            document.querySelectorAll('article,main,section,div').forEach((el) => pushNode(el, 0));

            let bestText = '';
            let bestEl = null;
            if (candidates.length) {
                candidates.sort((a, b) => b.score - a.score);
                bestText = candidates[0].text || '';
                bestEl = candidates[0].el || null;
            } else {
                bestText = norm(document.body ? document.body.innerText : '');
                bestEl = document.body || null;
            }

            let title = '';
            const titleSelectors = ['h1', '.chapter-title', '#chapter-title', 'main h1', 'article h1'];
            for (const sel of titleSelectors) {
                const el = document.querySelector(sel);
                if (!el) continue;
                title = norm(el.innerText || el.textContent || '');
                if (title) break;
            }
            if (!title) title = norm(document.title || '');

            const currentAnchors = buildAnchors(opts.currentTitle || title);
            const nextAnchors = buildAnchors(opts.nextTitle || '');
            const startEl = bestEl ? findTitleElement(bestEl, currentAnchors, null) : null;
            const endEl = bestEl ? findTitleElement(bestEl, nextAnchors, startEl) : null;
            const imageUrls = bestEl ? collectImages(bestEl, startEl, endEl) : [];

            return { title, text: bestText, imageUrls, url: location.href };
        }""",
        {
            "currentTitle": current_title,
            "nextTitle": next_title,
        },
    )
    title = normalize_text((payload or {}).get("title", ""))
    text = normalize_text((payload or {}).get("text", ""))
    image_urls = (payload or {}).get("imageUrls", []) or []
    page_url = (payload or {}).get("url", "")
    return title, text, image_urls, page_url


def wait_for_chapter_text(
    page,
    timeout_sec: float,
    current_title: str = "",
    next_title: str = "",
) -> tuple[str, str, list[str]]:
    deadline = time.monotonic() + timeout_sec
    best_title = ""
    best_text = ""
    best_images: list[str] = []
    best_len = 0
    found_current_once = False

    while time.monotonic() < deadline:
        page_title, raw_text, raw_images, payload_url = chapter_text_from_dom(
            page,
            current_title=current_title,
            next_title=next_title,
        )
        lines = clean_paragraphs(raw_text)

        sliced_lines, found_current = slice_lines_by_title_window(
            lines=lines,
            current_title=current_title,
            next_title=next_title,
            page_title=page_title,
        )

        if current_title and not found_current:
            page.wait_for_timeout(chapterReadyTimeoutSec * 1000)
            continue

        if found_current:
            found_current_once = True

        text = "\n\n".join(sliced_lines)
        current_len = len(text)
        normalized_images = unique_image_urls(raw_images, payload_url or page.url)

        if (current_len > best_len) or (
            current_len == best_len and len(normalized_images) > len(best_images)
        ):
            best_len = current_len
            best_title = page_title
            best_text = text
            best_images = normalized_images

        if current_len >= 120:
            return best_title, best_text, best_images

        page.wait_for_timeout(chapterReadyTimeoutSec * 1000)    

    if best_len >= 80:
        return best_title, best_text, best_images

    if current_title and not found_current_once:
        raise PlaywrightTimeoutError("current chapter title not found in page text")

    raise PlaywrightTimeoutError("chapter text not ready before timeout")


def guess_image_extension(url: str, content_type: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in IMAGE_EXT_BY_MIME:
        return IMAGE_EXT_BY_MIME[ct]
    path = urlparse(url).path.lower()
    for ext in IMAGE_MIME_BY_EXT:
        if path.endswith(ext):
            return ext
    return ".jpg"


def guess_image_mime(content_type: str, ext: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct.startswith("image/"):
        return ct
    return IMAGE_MIME_BY_EXT.get(ext.lower(), "image/jpeg")


def download_image_blob(session: requests.Session, url: str) -> tuple[bytes, str, str] | None:
    try:
        resp = session.get(url, timeout=(10, chapterReadyTimeoutSec), headers={"Referer": base_url})    
        resp.raise_for_status()
    except Exception:
        return None

    if not resp.content:
        return None

    content_type = resp.headers.get("Content-Type", "")
    ext = guess_image_extension(url, content_type)
    media_type = guess_image_mime(content_type, ext)
    return resp.content, media_type, ext


def chapter_to_html(chapter_title: str, chapter_text: str, image_files: list[str] | None = None) -> str:
    ps = []
    for line in chapter_text.splitlines():
        t = normalize_text(line)
        if t:
            ps.append(f"<p>{html.escape(t)}</p>")

    if image_files:
        ps.append("<hr/>")
        for img_file in image_files:
            ps.append(f"<p><img src='{html.escape(img_file)}' alt='image'/></p>")

    body = "\n".join(ps) if ps else "<p>(empty)</p>"
    return (
        "<html><head><meta charset='utf-8'/></head><body>"
        f"<h1>{html.escape(chapter_title)}</h1>"
        f"{body}"
        "</body></html>"
    )


def build_epub(
    book_meta: BookMeta,
    chapters: list[ChapterData],
    output_path: Path,
    session: requests.Session,
) -> None:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_language("zh")
    book.set_title(book_meta.title)
    if book_meta.author:
        book.add_author(book_meta.author)

    toc_items = []
    spine_items = ["nav"]

    image_file_by_url: dict[str, str] = {}
    image_count = 0

    for i, ch in enumerate(chapters, start=1):
        chapter_image_files: list[str] = []
        for img_url in unique_keep_order(ch.image_urls):
            file_name = image_file_by_url.get(img_url)
            if not file_name:
                blob = download_image_blob(session, img_url)
                if blob is None:
                    continue
                data, media_type, ext = blob
                image_count += 1
                file_name = f"images/img_{image_count:06d}{ext}"
                image_uid = f"img_{hashlib.sha1(img_url.encode('utf-8')).hexdigest()[:20]}"
                book.add_item(
                    epub.EpubImage(
                        uid=image_uid,
                        file_name=file_name,
                        media_type=media_type,
                        content=data,
                    )
                )
                image_file_by_url[img_url] = file_name
            chapter_image_files.append(file_name)

        chapter_image_files = unique_keep_order(chapter_image_files)
        item = epub.EpubHtml(
            title=ch.title,
            file_name=f"chapter_{i:05d}.xhtml",
            lang="zh",
            uid=f"chapter_{i:05d}",
        )
        item.content = chapter_to_html(ch.title, ch.text, chapter_image_files)
        book.add_item(item)
        toc_items.append(item)
        spine_items.append(item)

    book.toc = tuple(toc_items)
    book.spine = spine_items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), book, {})


def save_txt(book_meta: BookMeta, chapters: list[ChapterData], output_path: Path) -> None:
    lines = [book_meta.title]
    if book_meta.author:
        lines.append(f"Author: {book_meta.author}")
    lines.append("")
    for ch in chapters:
        lines.append(ch.title)
        lines.append(ch.text)
        if ch.image_urls:
            lines.append("[Images]")
            lines.extend(unique_keep_order(ch.image_urls))
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def get_cache_path(book_id: int) -> Path:
    return Path(cacheOutputDir) / f"book_{book_id}_cache.json"


def load_chapter_cache(book_id: int) -> dict[int, ChapterData]:
    cache_path = get_cache_path(book_id)
    if not cache_path.exists():
        return {}
    try:
        data = cache_path.read_text(encoding="utf-8")
        import json
        cached = json.loads(data)
        result = {}
        for cid, ch_data in cached.items():
            result[int(cid)] = ChapterData(
                title=ch_data.get("title", ""),
                text=ch_data.get("text", ""),
                url=ch_data.get("url", ""),
                chapter_id=ch_data.get("chapter_id", 0),
                image_urls=ch_data.get("image_urls", []),
            )
        return result
    except Exception:
        return {}


def save_chapter_cache(book_id: int, chapters: list[ChapterData]) -> None:
    cache_path = get_cache_path(book_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    cache_data = {}
    for ch in chapters:
        cache_data[ch.chapter_id] = {
            "title": ch.title,
            "text": ch.text,
            "url": ch.url,
            "chapter_id": ch.chapter_id,
            "image_urls": ch.image_urls,
        }
    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")


def sleep_between(min_sec: float, max_sec: float) -> None:
    delay = max(min_sec, min(max_sec, random.uniform(min_sec, max_sec)))
    time.sleep(delay)


def print_progress(current: int, total: int, title: str) -> None:
    print(f"[{current}/{total}] {title}")


def download_chapters_with_browser(
    chapters: list[ChapterRef],
    cookie_line: str,
    chapter_cache: dict[int, ChapterData],
) -> tuple[list[ChapterData], list[FailedChapter], dict[int, ChapterData]]:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")

    results: list[ChapterData] = []
    failed: list[FailedChapter] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=DEFAULT_HEADERS["User-Agent"], locale="zh-CN")
        if cookie_line:
            context.set_extra_http_headers({"Cookie": cookie_line})
        page = context.new_page()

        total = len(chapters)
        for i, ch in enumerate(chapters, start=1):
            if ch.chapter_id in chapter_cache:
                cached_ch = chapter_cache[ch.chapter_id]
                results.append(cached_ch)
                print(f"  [=] cached: {cached_ch.title} ({len(cached_ch.text)} chars, images={len(cached_ch.image_urls)})")
                continue
            print_progress(i, total, f"Fetching {ch.url}")
            done = False
            last_error = ""
            for attempt in range(1, retryPerChapter + 2):
                try:
                    page.goto(ch.url, wait_until="domcontentloaded", timeout=pageGotoTimeoutMs)

                    if i == 1 and firstChapterExtraWaitSec > 0:
                        page.wait_for_timeout(int(firstChapterExtraWaitSec * 1000))
                    sleep_between(chapterDelayMinSec, chapterDelayMaxSec)

                    next_title = chapters[i].title if i < total else ""
                    title, text, image_urls = wait_for_chapter_text(
                        page,
                        chapterReadyTimeoutSec,
                        current_title=ch.title,
                        next_title=next_title,
                    )
                    if ch.title:
                        title = ch.title
                    elif not title:
                        title = f"Chapter {i}"
                    if not text:
                        raise RuntimeError("empty chapter text")

                    chapter_data = ChapterData(
                        title=title,
                        text=text,
                        url=ch.url,
                        chapter_id=ch.chapter_id,
                        image_urls=image_urls,
                    )
                    results.append(chapter_data)
                    chapter_cache[ch.chapter_id] = chapter_data
                    print(f"  [+] ok: {title} ({len(text)} chars, images={len(image_urls)})")
                    done = True
                    break
                except Exception as e:
                    last_error = str(e)
                    print(f"  [!] attempt {attempt} failed: {last_error}")
                    if attempt <= retryPerChapter:
                        time.sleep(1.0 * attempt)
                        continue
                    if keepFailedChapterPlaceholder:
                        title = ch.title or f"Chapter {i}"
                        text = f"[Failed to extract]\nURL: {ch.url}\nReason: {last_error}"
                        results.append(
                            ChapterData(
                                title=title,
                                text=text,
                                url=ch.url,
                                chapter_id=ch.chapter_id,
                                image_urls=[],
                            )
                        )
                    break

            if not done:
                failed.append(
                    FailedChapter(
                        index=i,
                        title=ch.title or f"Chapter {i}",
                        url=ch.url,
                        chapter_id=ch.chapter_id,
                        reason=last_error or "unknown",
                    )
                )
                if not keepFailedChapterPlaceholder:
                    print(f"  [x] skip chapter: {ch.url}")

        context.close()
        browser.close()
    return results, failed, chapter_cache
def ensure_domain_consistency() -> None:
    parsed_base = urlparse(base_url)
    parsed_book = urlparse(bookURL)
    if parsed_base.scheme != parsed_book.scheme or parsed_base.netloc != parsed_book.netloc:
        raise RuntimeError("base_url and bookURL must use the same scheme+domain")


def main() -> None:
    ensure_domain_consistency()

    cookie_line = read_cookie_line(cookieFilePath)
    if cookie_line:
        print("[*] Cookie loaded from novalpie.txt")
    else:
        print("[*] novalpie.txt not found or empty, continue without cookie")

    try:
        book_id, start_chapter_id = parse_book_url(bookURL)
    except Exception as e:
        print(f"[x] Invalid bookURL: {e}")
        sys.exit(1)

    session = make_session(cookie_line)

    chapter_cache = load_chapter_cache(book_id)
    if chapter_cache:
        print(f"[*] Loaded {len(chapter_cache)} cached chapters")

    print(f"[*] book_id={book_id}, start_chapter_id={start_chapter_id}")
    print("[*] Fetching chapter list ...")

    chapter_refs: list[ChapterRef] = []
    try:
        chapter_refs = fetch_chapter_list_via_api(session, book_id)
        print(f"[*] Chapter list source: API, count={len(chapter_refs)}")
    except Exception as e:
        print(f"[!] API chapter list failed: {e}")

    if not chapter_refs:
        chapter_refs = fetch_chapter_list_via_html(session, book_id, bookURL)
        print(f"[*] Chapter list source: HTML fallback, count={len(chapter_refs)}")

    if not chapter_refs:
        print("[x] No chapter list found. Please check URL/cookie.")
        sys.exit(2)

    start_idx = pick_start_index(chapter_refs, start_chapter_id, startFromCurrentChapter)
    chapter_refs = chapter_refs[start_idx:]

    if maxChapters > 0:
        chapter_refs = chapter_refs[:maxChapters]

    if not chapter_refs:
        print("[x] No chapters left after filtering.")
        sys.exit(3)

    meta = fetch_book_meta(session, book_id, bookURL)
    print(f"[*] Book title: {meta.title}")
    if meta.author:
        print(f"[*] Author: {meta.author}")
    print(f"[*] Chapters to download: {len(chapter_refs)}")

    chapters, failed_chapters, chapter_cache = download_chapters_with_browser(chapter_refs, cookie_line, chapter_cache)
    if not chapters:
        print("[x] All chapter downloads failed; no output generated.")
        sys.exit(4)

    save_chapter_cache(book_id, list(chapter_cache.values()))
    print(f"[*] Cached {len(chapter_cache)} chapters")

    Path(epubOutputDir).mkdir(parents=True, exist_ok=True)
    Path(txtOutputDir).mkdir(parents=True, exist_ok=True)

    file_stem = clean_filename(meta.title)

    if failed_chapters:
        failed_path = Path(txtOutputDir) / f"{file_stem}_failed.txt"
        lines: list[str] = []
        lines.append(f"Failed Chapters Report")
        lines.append(f"Book: {meta.title}")
        lines.append(f"Author: {meta.author or 'unknown'}")
        lines.append(f"Total failed: {len(failed_chapters)}")
        lines.append("=" * 60)
        for fc in failed_chapters:
            lines.append(f"")
            lines.append(f"  [#{fc.index}] {fc.title}")
            lines.append(f"  URL: {fc.url}")
            lines.append(f"  Chapter ID: {fc.chapter_id}")
            lines.append(f"  Reason: {fc.reason}")
        lines.append(f"")
        lines.append("=" * 60)
        failed_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[*] Failed chapters report: {failed_path.resolve()}")

    epub_path = Path(epubOutputDir) / f"{file_stem}.epub"
    txt_path = Path(txtOutputDir) / f"{file_stem}.txt"

    build_epub(meta, chapters, epub_path, session)
    save_txt(meta, chapters, txt_path)

    print("[*] Done.")
    print(f"[*] EPUB: {epub_path.resolve()}")
    print(f"[*] TXT : {txt_path.resolve()}")
    print(f"[*] Success chapters: {len(chapters)}")
    print(f"[*] Failed chapters: {len(failed_chapters)}")


if __name__ == "__main__":
    main()







