import html
import hashlib
from pathlib import Path
from typing import List

from ebooklib import epub

from . import config
from . import utils
from . import network

def chapter_to_html(chapter_title: str, chapter_text: str, image_files: List[str] = None) -> str:
    ps = []
    for line in chapter_text.splitlines():
        t = utils.normalize_text(line)
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
    book_meta: config.BookMeta,
    chapters: List[config.ChapterData],
    output_path: Path,
    session,
) -> None:
    book = epub.EpubBook()
    import uuid
    book.set_identifier(str(uuid.uuid4()))
    book.set_language("zh")
    book.set_title(book_meta.title)
    if book_meta.author:
        book.add_author(book_meta.author)
    if book_meta.description:
        book.add_metadata('DC', 'description', book_meta.description)

    toc_items = []
    spine_items = ["nav"]

    image_file_by_url: dict[str, str] = {}
    image_count = 0

    for i, ch in enumerate(chapters, start=1):
        chapter_image_files: List[str] = []
        for img_url in utils.unique_keep_order(ch.image_urls):
            file_name = image_file_by_url.get(img_url)
            if not file_name:
                blob = network.download_image_blob(session, img_url)
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

        chapter_image_files = utils.unique_keep_order(chapter_image_files)

        chapter_text = ch.text
        if i == 1 and book_meta.tags:
            tags_text = "标签：" + "，".join(book_meta.tags)
            chapter_text = tags_text + "\n\n" + chapter_text

        item = epub.EpubHtml(
            title=ch.title,
            file_name=f"chapter_{i:05d}.xhtml",
            lang="zh",
            uid=f"chapter_{i:05d}",
        )
        item.content = chapter_to_html(ch.title, chapter_text, chapter_image_files)
        book.add_item(item)
        spine_items.append(item)
        toc_items.append(item)

    if book_meta.tags:
        for tag in book_meta.tags:
            book.add_metadata('DC', 'subject', tag)

    book.toc = tuple(toc_items)
    book.spine = spine_items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), book, {})

def save_txt(book_meta: config.BookMeta, chapters: List[config.ChapterData], output_path: Path) -> None:
    lines = [book_meta.title]
    if book_meta.author:
        lines.append(f"Author: {book_meta.author}")
    lines.append("")
    for ch in chapters:
        lines.append(ch.title)
        lines.append(ch.text)
        if ch.image_urls:
            lines.append("[Images]")
            lines.extend(utils.unique_keep_order(ch.image_urls))
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")

def save_failed_report(
    book_meta: config.BookMeta,
    failed_chapters: List[config.FailedChapter],
    output_path: Path
) -> None:
    lines = ["Failed Chapters Report"]
    lines.append(f"Book: {book_meta.title}")
    lines.append(f"Author: {book_meta.author or 'unknown'}")
    lines.append(f"Total failed: {len(failed_chapters)}")
    lines.append("=" * 60)
    for fc in failed_chapters:
        lines.append("")
        lines.append(f"  [#{fc.index}] {fc.title}")
        lines.append(f"  URL: {fc.url}")
        lines.append(f"  Chapter ID: {fc.chapter_id}")
        lines.append(f"  Reason: {fc.reason}")
    lines.append("")
    lines.append("=" * 60)
    output_path.write_text("\n".join(lines), encoding="utf-8")
