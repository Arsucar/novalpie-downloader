# coding=utf-8
"""
novalpie.cc novel downloader

How to use:
1) Edit config values in config.py (bookURL, maxChapters, etc.).
2) Optional: put cookie string in ./novalpie.txt first line.
3) Run:
   python novalpie.py

Dependencies:
  pip install requests beautifulsoup4 lxml ebooklib playwright
  playwright install chromium
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from novalpie import config
from novalpie import utils
from novalpie import network
from novalpie import browser
from novalpie import cache
from novalpie import exporters


def ensure_domain_consistency() -> None:
    parsed_base = urlparse(config.base_url)
    parsed_book = urlparse(config.bookURL)
    if parsed_base.scheme != parsed_book.scheme or parsed_base.netloc != parsed_book.netloc:
        raise RuntimeError("base_url and bookURL must use the same scheme+domain")


def main() -> None:
    ensure_domain_consistency()

    cookie_line = utils.read_cookie_line(config.cookieFilePath)
    if cookie_line:
        print("[*] Cookie loaded from novalpie.txt")
    else:
        print("[*] novalpie.txt not found or empty, continue without cookie")

    try:
        book_id, start_chapter_id = network.parse_book_url(config.bookURL)
    except Exception as e:
        print(f"[x] Invalid bookURL: {e}")
        sys.exit(1)

    session = network.make_session(cookie_line)

    chapter_cache = cache.load_chapter_cache(book_id)
    if chapter_cache:
        print(f"[*] Loaded {len(chapter_cache)} cached chapters")

    print(f"[*] book_id={book_id}, start_chapter_id={start_chapter_id}")
    print("[*] Fetching chapter list ...")

    chapter_refs = []
    try:
        chapter_refs = network.fetch_chapter_list_via_api(session, book_id)
        print(f"[*] Chapter list source: API, count={len(chapter_refs)}")
    except Exception as e:
        print(f"[!] API chapter list failed: {e}")

    if not chapter_refs:
        chapter_refs = network.fetch_chapter_list_via_html(session, book_id, config.bookURL)
        print(f"[*] Chapter list source: HTML fallback, count={len(chapter_refs)}")

    if not chapter_refs:
        print("[x] No chapter list found. Please check URL/cookie.")
        sys.exit(2)

    start_idx = utils.pick_start_index(chapter_refs, start_chapter_id, config.startFromCurrentChapter)
    chapter_refs = chapter_refs[start_idx:]

    if config.maxChapters > 0:
        chapter_refs = chapter_refs[:config.maxChapters]

    if not chapter_refs:
        print("[x] No chapters left after filtering.")
        sys.exit(3)

    meta = network.fetch_book_meta(session, book_id, config.bookURL)
    print(f"[*] Book title: {meta.title}")
    if meta.author:
        print(f"[*] Author: {meta.author}")
    print(f"[*] Chapters to download: {len(chapter_refs)}")

    chapters, failed_chapters, chapter_cache = browser.download_chapters_with_browser(
        chapter_refs, cookie_line, chapter_cache, book_id=book_id
    )
    if not chapters:
        print("[x] All chapter downloads failed; no output generated.")
        sys.exit(4)

    cache.save_chapter_cache(book_id, list(chapter_cache.values()))
    print(f"[*] Cached {len(chapter_cache)} chapters")

    Path(config.epubOutputDir).mkdir(parents=True, exist_ok=True)
    Path(config.txtOutputDir).mkdir(parents=True, exist_ok=True)

    file_stem = utils.clean_filename(meta.title)

    if failed_chapters:
        failed_path = Path(config.txtOutputDir) / f"{file_stem}_failed.txt"
        exporters.save_failed_report(meta, failed_chapters, failed_path)
        print(f"[*] Failed chapters report: {failed_path.resolve()}")

    epub_path = Path(config.epubOutputDir) / f"{file_stem}.epub"
    txt_path = Path(config.txtOutputDir) / f"{file_stem}.txt"

    exporters.build_epub(meta, chapters, epub_path, session)
    exporters.save_txt(meta, chapters, txt_path)

    print("[*] Done.")
    print(f"[*] EPUB: {epub_path.resolve()}")
    print(f"[*] TXT : {txt_path.resolve()}")
    print(f"[*] Success chapters: {len(chapters)}")
    print(f"[*] Failed chapters: {len(failed_chapters)}")


if __name__ == "__main__":
    main()