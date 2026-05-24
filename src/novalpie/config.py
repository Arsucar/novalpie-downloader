from dataclasses import dataclass, field
import re

# Config (edit here)

# bookURL：起始章节链接（必改）
bookURL = "https://novalpie.cc/book/328287/1176631"

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

COMMENT_SECTION_START_RE = re.compile(r"^章节讨论(?:\s*\(\d+\))?$")
COMMENT_NOISE_RES = [
    re.compile(r"^展开评论$"),
    re.compile(r"^暂无评论.*$"),
    re.compile(r"^\(\d+\)$"),
]

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
    description: str = ""
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""

def run() -> None:
    import run
    run.main()

if __name__ == "__main__":
    run()