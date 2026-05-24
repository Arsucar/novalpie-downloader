import json
from pathlib import Path
from typing import Dict, List, Optional

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

def append_chapter_to_cache(book_id: int, chapter: config.ChapterData, existing_cache: Optional[dict] = None) -> dict:
    """增量缓存：每下载完一章立即追加到缓存文件
    
    Args:
        existing_cache: 可选的已加载缓存数据，避免重复读取文件。
                       如果提供，将直接使用该数据并返回更新后的缓存。
                       如果不提供，将从文件读取。
    Returns:
        更新后的缓存数据字典
    """
    cache_path = get_cache_path(book_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if existing_cache is not None:
        cache_data = existing_cache
    else:
        # 加载现有缓存
        cache_data = {}
        if cache_path.exists():
            try:
                data = cache_path.read_text(encoding="utf-8")
                cache_data = json.loads(data)
            except Exception:
                cache_data = {}

    # 追加/更新当前章节
    cache_data[chapter.chapter_id] = {
        "title": chapter.title,
        "text": chapter.text,
        "url": chapter.url,
        "chapter_id": chapter.chapter_id,
        "image_urls": chapter.image_urls,
    }

    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache_data
