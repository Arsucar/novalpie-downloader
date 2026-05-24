import json
from pathlib import Path
from typing import Dict, List

from . import config
from . import utils

def get_cache_path(book_id: int) -> Path:
    return Path(config.cacheOutputDir) / f"book_{book_id}_cache.json"

def load_chapter_cache(book_id: int) -> Dict[int, config.ChapterData]:
    cache_path = get_cache_path(book_id)
    if not cache_path.exists():
        return {}
    try:
        data = cache_path.read_text(encoding="utf-8")
        cached = json.loads(data)
        result = {}
        for cid, ch_data in cached.items():
            result[int(cid)] = config.ChapterData(
                title=ch_data.get("title", ""),
                text=ch_data.get("text", ""),
                url=ch_data.get("url", ""),
                chapter_id=ch_data.get("chapter_id", 0),
                image_urls=ch_data.get("image_urls", []),
            )
        return result
    except Exception:
        return {}

def save_chapter_cache(book_id: int, chapters: List[config.ChapterData]) -> None:
    cache_path = get_cache_path(book_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
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
