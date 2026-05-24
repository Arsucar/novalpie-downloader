import re
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any
import config

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

def absolute_url(u: str) -> str:
    return urljoin(config.base_url.rstrip("/") + "/", u)

def is_loading_text(text: str) -> bool:
    t = normalize_text(text).lower()
    if not t:
        return True
    if any(h in t for h in config.LOADING_HINTS) and len(t) <= 220:
        return True
    return False

def clean_paragraphs(text: str) -> list[str]:
    lines: list[str] = []
    for raw in normalize_text(text).splitlines():
        line = normalize_text(raw)
        if len(line) < 2:
            continue
        if config.DROP_LINE_RE.match(line):
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

def normalize_title_key(text: str) -> str:
    t = normalize_text(text)
    t = re.sub(r'[\s"\'“”‘’《》〈〉【】\[\]\(\)（）:：,，.!！?？·、\-—_]+', "", t)
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
    if config.COMMENT_SECTION_START_RE.match(t) is not None:
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
    for rgx in config.COMMENT_NOISE_RES:
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

def pick_start_index(chapters: list[config.ChapterRef], start_chapter_id: int, from_current: bool) -> int:
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

def guess_image_extension(url: str, content_type: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in config.IMAGE_EXT_BY_MIME:
        return config.IMAGE_EXT_BY_MIME[ct]
    path = urlparse(url).path.lower()
    for ext in config.IMAGE_MIME_BY_EXT:
        if path.endswith(ext):
            return ext
    return ".jpg"

def guess_image_mime(content_type: str, ext: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct.startswith("image/"):
        return ct
    return config.IMAGE_MIME_BY_EXT.get(ext.lower(), "image/jpeg")

def sleep_between(min_sec: float, max_sec: float) -> None:
    delay = max(min_sec, min(max_sec, random.uniform(min_sec, max_sec)))
    time.sleep(delay)

def print_progress(current: int, total: int, title: str) -> None:
    print(f"[{current}/{total}] {title}")
