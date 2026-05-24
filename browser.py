import time
from typing import Tuple

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:
    PlaywrightTimeoutError = Exception
    sync_playwright = None

import config
import utils

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
                const cls = ((el.className || '') + ' ' + ((el.id || '')).toLowerCase();
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
    title = utils.normalize_text((payload or {}).get("title", ""))
    text = utils.normalize_text((payload or {}).get("text", ""))
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
        lines = utils.clean_paragraphs(raw_text)

        sliced_lines, found_current = utils.slice_lines_by_title_window(
            lines=lines,
            current_title=current_title,
            next_title=next_title,
            page_title=page_title,
        )

        if current_title and not found_current:
            page.wait_for_timeout(config.chapterReadyTimeoutSec * 1000)
            continue

        if found_current:
            found_current_once = True

        text = "\n\n".join(sliced_lines)
        current_len = len(text)
        normalized_images = utils.unique_image_urls(raw_images, payload_url or page.url)

        if (current_len > best_len) or (
            current_len == best_len and len(normalized_images) > len(best_images)
        ):
            best_len = current_len
            best_title = page_title
            best_text = text
            best_images = normalized_images

        if current_len >= 120:
            return best_title, best_text, best_images

        page.wait_for_timeout(config.chapterReadyTimeoutSec * 1000)

    if best_len >= 80:
        return best_title, best_text, best_images

    if current_title and not found_current_once:
        raise PlaywrightTimeoutError("current chapter title not found in page text")

    raise PlaywrightTimeoutError("chapter text not ready before timeout")

def download_chapters_with_browser(
    chapters: list[config.ChapterRef],
    cookie_line: str,
    chapter_cache: dict[int, config.ChapterData],
) -> tuple[list[config.ChapterData], list[config.FailedChapter], dict[int, config.ChapterData]]:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")

    results: list[config.ChapterData] = []
    failed: list[config.FailedChapter] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        context = browser.new_context(user_agent=config.DEFAULT_HEADERS["User-Agent"], locale="zh-CN")
        if cookie_line:
            context.set_extra_http_headers({"Cookie": cookie_line})
        page = context.new_page()

        total = len(chapters)
        for i, ch in enumerate(chapters, start=1):
            if ch.chapter_id in chapter_cache:
                cached_ch = chapter_cache[ch.chapter_id]
                results.append(cached_ch)
                print(f"  [=] cached: {cached_ch.title} ({len(cached_ch.text)} chars, images={len(cached_ch.image_urls)}")
                continue
            utils.print_progress(i, total, f"Fetching {ch.url}")
            done = False
            last_error = ""
            for attempt in range(1, config.retryPerChapter + 2):
                try:
                    page.goto(ch.url, wait_until="domcontentloaded", timeout=config.pageGotoTimeoutMs)

                    if i == 1 and config.firstChapterExtraWaitSec > 0:
                        page.wait_for_timeout(int(config.firstChapterExtraWaitSec * 1000))
                    utils.sleep_between(config.chapterDelayMinSec, config.chapterDelayMaxSec)

                    next_title = chapters[i].title if i < total else ""
                    title, text, image_urls = wait_for_chapter_text(
                        page,
                        config.chapterReadyTimeoutSec,
                        current_title=ch.title,
                        next_title=next_title,
                    )
                    if ch.title:
                        title = ch.title
                    elif not title:
                        title = f"Chapter {i}"
                    if not text:
                        raise RuntimeError("empty chapter text")

                    chapter_data = config.ChapterData(
                        title=title,
                        text=text,
                        url=ch.url,
                        chapter_id=ch.chapter_id,
                        image_urls=image_urls,
                    )
                    results.append(chapter_data)
                    chapter_cache[ch.chapter_id] = chapter_data
                    print(f"  [+] ok: {title} ({len(text)} chars, images={len(image_urls)}")
                    done = True
                    break
                except Exception as e:
                    last_error = str(e)
                    print(f"  [!] attempt {attempt} failed: {last_error}")
                    if attempt <= config.retryPerChapter:
                        time.sleep(1.0 * attempt)
                        continue
                    if config.keepFailedChapterPlaceholder:
                        title = ch.title or f"Chapter {i}"
                        text = f"[Failed to extract]\nURL: {ch.url}\nReason: {last_error}"
                        results.append(
                            config.ChapterData(
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
                    config.FailedChapter(
                        index=i,
                        title=ch.title or f"Chapter {i}",
                        url=ch.url,
                        chapter_id=ch.chapter_id,
                        reason=last_error or "unknown",
                    )
                )
                if not config.keepFailedChapterPlaceholder:
                    print(f"  [x] skip chapter: {ch.url}")

        context.close()
        browser.close()
    return results, failed, chapter_cache
