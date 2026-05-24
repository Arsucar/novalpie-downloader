# coding=utf-8
"""NovalPie GUI - 基于 customtkinter 的图形界面"""

from __future__ import annotations

import io
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import customtkinter as ctk

from . import config
from . import utils
from . import network
from . import browser
from . import cache
from . import exporters


class TextHandler(io.TextIOBase):
    """将 write 调用转发到 GUI 日志区域"""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self.buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self.callback(text)
        return len(text)

    def flush(self):
        pass


class NovalPieApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NovalPie Downloader")
        self.geometry("780x680")
        self.minsize(680, 560)

        self._stop_event = threading.Event()
        self._running = False

        self._build_ui()
        self._load_config_to_ui()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        # 顶部标题
        title_label = ctk.CTkLabel(
            self, text="NovalPie 小说下载器",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        title_label.pack(pady=(14, 4))

        # 主容器
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        # ── 基本设置 ──
        self._section(main_frame, "基本设置")

        self.entry_book_url = self._labeled_entry(
            main_frame, "书籍章节链接 (bookURL):", config.bookURL
        )
        self.entry_base_url = self._labeled_entry(
            main_frame, "站点根地址 (base_url):", config.base_url
        )
        self.entry_cookie = self._labeled_entry(
            main_frame, "Cookie 文件路径:", config.cookieFilePath
        )

        # ── 下载设置 ──
        self._section(main_frame, "下载设置")

        row1 = ctk.CTkFrame(main_frame, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        self.entry_delay_min = self._labeled_entry_inline(
            row1, "章节间隔(秒) 最小:", str(config.chapterDelayMinSec)
        )
        self.entry_delay_max = self._labeled_entry_inline(
            row1, "最大:", str(config.chapterDelayMaxSec)
        )

        row2 = ctk.CTkFrame(main_frame, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        self.entry_timeout = self._labeled_entry_inline(
            row2, "章节超时(秒):", str(config.chapterReadyTimeoutSec)
        )
        self.entry_retry = self._labeled_entry_inline(
            row2, "重试次数:", str(config.retryPerChapter)
        )

        row3 = ctk.CTkFrame(main_frame, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        self.entry_max_chapters = self._labeled_entry_inline(
            row3, "最大章节数 (0=不限):", str(config.maxChapters)
        )
        self.entry_first_wait = self._labeled_entry_inline(
            row3, "首章额外等待(秒):", str(config.firstChapterExtraWaitSec)
        )

        # ── 选项开关 ──
        self._section(main_frame, "选项")

        opt_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        opt_frame.pack(fill="x", pady=2)

        self.var_headless = ctk.BooleanVar(value=config.headless)
        ctk.CTkCheckBox(opt_frame, text="无头模式 (headless)", variable=self.var_headless).pack(
            side="left", padx=(0, 16)
        )

        self.var_from_current = ctk.BooleanVar(value=config.startFromCurrentChapter)
        ctk.CTkCheckBox(opt_frame, text="从当前章节开始", variable=self.var_from_current).pack(
            side="left", padx=(0, 16)
        )

        self.var_keep_failed = ctk.BooleanVar(value=config.keepFailedChapterPlaceholder)
        ctk.CTkCheckBox(opt_frame, text="保留失败章节占位", variable=self.var_keep_failed).pack(
            side="left"
        )

        # ── 输出目录 ──
        self._section(main_frame, "输出目录")

        self.entry_epub_dir = self._labeled_entry(
            main_frame, "EPUB 输出目录:", config.epubOutputDir
        )
        self.entry_txt_dir = self._labeled_entry(
            main_frame, "TXT 输出目录:", config.txtOutputDir
        )
        self.entry_cache_dir = self._labeled_entry(
            main_frame, "缓存目录:", config.cacheOutputDir
        )

        # ── 进度条 ──
        self._section(main_frame, "进度")

        self.progress_bar = ctk.CTkProgressBar(main_frame)
        self.progress_bar.pack(fill="x", pady=(4, 2))
        self.progress_bar.set(0)

        self.label_status = ctk.CTkLabel(main_frame, text="就绪", anchor="w")
        self.label_status.pack(fill="x")

        # ── 日志区域 ──
        self._section(main_frame, "日志")

        self.text_log = ctk.CTkTextbox(main_frame, height=180)
        self.text_log.pack(fill="both", expand=True, pady=(4, 4))

        # ── 按钮栏 ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))

        self.btn_start = ctk.CTkButton(
            btn_frame, text="开始下载", fg_color="#2ecc71", hover_color="#27ae60",
            command=self._on_start,
        )
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            btn_frame, text="停止", fg_color="#e74c3c", hover_color="#c0392b",
            command=self._on_stop, state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(0, 8))

        self.btn_clear = ctk.CTkButton(
            btn_frame, text="清空日志", command=self._on_clear_log,
            fg_color="transparent", border_width=1,
        )
        self.btn_clear.pack(side="left")

    # ── UI 辅助方法 ─────────────────────────────────────────

    @staticmethod
    def _section(parent, text: str):
        label = ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        label.pack(fill="x", pady=(12, 2))
        sep = ctk.CTkFrame(parent, height=1)
        sep.pack(fill="x", pady=(0, 4))

    @staticmethod
    def _labeled_entry(parent, label_text: str, default: str) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=2)
        ctk.CTkLabel(frame, text=label_text, width=180, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(frame)
        entry.pack(side="left", fill="x", expand=True)
        entry.insert(0, default)
        return entry

    @staticmethod
    def _labeled_entry_inline(parent, label_text: str, default: str) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label_text, anchor="w").pack(side="left", padx=(0, 4))
        entry = ctk.CTkEntry(parent, width=80)
        entry.pack(side="left", padx=(0, 12))
        entry.insert(0, default)
        return entry

    # ── 配置读写 ────────────────────────────────────────────

    def _load_config_to_ui(self):
        """config.py 中的默认值已在 _build_ui 时填入"""
        pass

    def _apply_ui_to_config(self) -> list[str]:
        """将 UI 值写入 config 模块，返回错误列表"""
        errors: list[str] = []

        config.bookURL = self.entry_book_url.get().strip()
        config.base_url = self.entry_base_url.get().strip()
        config.cookieFilePath = self.entry_cookie.get().strip()

        try:
            config.chapterDelayMinSec = float(self.entry_delay_min.get().strip())
        except ValueError:
            errors.append("章节间隔最小值无效")
        try:
            config.chapterDelayMaxSec = float(self.entry_delay_max.get().strip())
        except ValueError:
            errors.append("章节间隔最大值无效")
        try:
            config.chapterReadyTimeoutSec = float(self.entry_timeout.get().strip())
        except ValueError:
            errors.append("章节超时无效")
        try:
            config.retryPerChapter = int(self.entry_retry.get().strip())
        except ValueError:
            errors.append("重试次数无效")
        try:
            config.maxChapters = int(self.entry_max_chapters.get().strip())
        except ValueError:
            errors.append("最大章节数无效")
        try:
            config.firstChapterExtraWaitSec = float(self.entry_first_wait.get().strip())
        except ValueError:
            errors.append("首章等待时间无效")

        config.headless = self.var_headless.get()
        config.startFromCurrentChapter = self.var_from_current.get()
        config.keepFailedChapterPlaceholder = self.var_keep_failed.get()

        config.epubOutputDir = self.entry_epub_dir.get().strip()
        config.txtOutputDir = self.entry_txt_dir.get().strip()
        config.cacheOutputDir = self.entry_cache_dir.get().strip()

        return errors

    # ── 日志输出 ────────────────────────────────────────────

    def _log(self, text: str):
        def _append():
            self.text_log.insert("end", text)
            self.text_log.see("end")
        self.after(0, _append)

    def _set_status(self, text: str):
        def _update():
            self.label_status.configure(text=text)
        self.after(0, _update)

    def _set_progress(self, value: float):
        def _update():
            self.progress_bar.set(value)
        self.after(0, _update)

    # ── 按钮回调 ────────────────────────────────────────────

    def _on_start(self):
        errors = self._apply_ui_to_config()
        if errors:
            self._log("\n".join(f"[x] {e}" for e in errors) + "\n")
            return

        if not config.bookURL:
            self._log("[x] 请填写书籍章节链接\n")
            return

        self._stop_event.clear()
        self._running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_progress(0)
        self._set_status("下载中...")

        t = threading.Thread(target=self._run_download, daemon=True)
        t.start()

    def _on_stop(self):
        self._stop_event.set()
        self._set_status("正在停止...")
        self._log("[!] 用户请求停止\n")

    def _on_clear_log(self):
        self.text_log.delete("1.0", "end")

    # ── 下载逻辑（线程） ───────────────────────────────────

    def _run_download(self):
        # 重定向 stdout/stderr 到日志
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        handler = TextHandler(self._log)
        sys.stdout = handler
        sys.stderr = handler

        try:
            self._do_download()
        except Exception as e:
            print(f"[x] 未预期的错误: {e}")
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self._running = False
            self.after(0, self._download_finished)

    def _do_download(self):
        # 域名一致性检查
        parsed_base = urlparse(config.base_url)
        parsed_book = urlparse(config.bookURL)
        if parsed_base.scheme != parsed_book.scheme or parsed_base.netloc != parsed_book.netloc:
            print("[x] base_url 和 bookURL 域名不一致")
            return

        cookie_line = utils.read_cookie_line(config.cookieFilePath)
        if cookie_line:
            print("[*] Cookie 已加载")
        else:
            print("[*] 未找到 Cookie 文件，继续无 Cookie 模式")

        try:
            book_id, start_chapter_id = network.parse_book_url(config.bookURL)
        except Exception as e:
            print(f"[x] 无效的 bookURL: {e}")
            return

        session = network.make_session(cookie_line)

        chapter_cache = cache.load_chapter_cache(book_id)
        if chapter_cache:
            print(f"[*] 已加载 {len(chapter_cache)} 个缓存章节")

        print(f"[*] book_id={book_id}, start_chapter_id={start_chapter_id}")
        print("[*] 正在获取章节列表...")

        chapter_refs = []
        try:
            chapter_refs = network.fetch_chapter_list_via_api(session, book_id)
            print(f"[*] 章节列表来源: API, 数量={len(chapter_refs)}")
        except Exception as e:
            print(f"[!] API 获取失败: {e}")

        if not chapter_refs:
            chapter_refs = network.fetch_chapter_list_via_html(session, book_id, config.bookURL)
            print(f"[*] 章节列表来源: HTML, 数量={len(chapter_refs)}")

        if not chapter_refs:
            print("[x] 未找到章节列表，请检查链接和 Cookie")
            return

        start_idx = utils.pick_start_index(chapter_refs, start_chapter_id, config.startFromCurrentChapter)
        chapter_refs = chapter_refs[start_idx:]

        if config.maxChapters > 0:
            chapter_refs = chapter_refs[:config.maxChapters]

        if not chapter_refs:
            print("[x] 过滤后无章节可下载")
            return

        meta = network.fetch_book_meta(session, book_id, config.bookURL)
        print(f"[*] 书名: {meta.title}")
        if meta.author:
            print(f"[*] 作者: {meta.author}")
        print(f"[*] 待下载章节: {len(chapter_refs)}")

        total = len(chapter_refs)

        # Monkey-patch print_progress 以更新进度条
        _orig_print_progress = utils.print_progress
        def _gui_print_progress(current: int, total: int, title: str):
            _orig_print_progress(current, total, title)
            self._set_progress(current / total if total > 0 else 0)
            self._set_status(f"下载中 ({current}/{total}) - {title}")
        utils.print_progress = _gui_print_progress

        # Monkey-patch sleep_between 以支持停止
        _orig_sleep = utils.sleep_between
        def _checkable_sleep(min_sec: float, max_sec: float):
            delay = max(min_sec, min(max_sec, __import__("random").uniform(min_sec, max_sec)))
            # 分段 sleep 以便及时响应停止
            step = 0.2
            elapsed = 0.0
            while elapsed < delay:
                if self._stop_event.is_set():
                    return
                s = min(step, delay - elapsed)
                __import__("time").sleep(s)
                elapsed += s
        utils.sleep_between = _checkable_sleep

        try:
            chapters, failed_chapters, chapter_cache = browser.download_chapters_with_browser(
                chapter_refs, cookie_line, chapter_cache
            )
        finally:
            utils.print_progress = _orig_print_progress
            utils.sleep_between = _orig_sleep

        if self._stop_event.is_set():
            print("[!] 下载已被用户停止")
            if chapters:
                self._save_output(meta, chapters, failed_chapters, chapter_cache, book_id, session)
            return

        if not chapters:
            print("[x] 所有章节下载失败，无输出")
            return

        self._save_output(meta, chapters, failed_chapters, chapter_cache, book_id, session)

    def _save_output(self, meta, chapters, failed_chapters, chapter_cache, book_id, session):
        cache.save_chapter_cache(book_id, list(chapter_cache.values()))
        print(f"[*] 已缓存 {len(chapter_cache)} 个章节")

        Path(config.epubOutputDir).mkdir(parents=True, exist_ok=True)
        Path(config.txtOutputDir).mkdir(parents=True, exist_ok=True)

        file_stem = utils.clean_filename(meta.title)

        if failed_chapters:
            failed_path = Path(config.txtOutputDir) / f"{file_stem}_failed.txt"
            exporters.save_failed_report(meta, failed_chapters, failed_path)
            print(f"[*] 失败报告: {failed_path.resolve()}")

        epub_path = Path(config.epubOutputDir) / f"{file_stem}.epub"
        txt_path = Path(config.txtOutputDir) / f"{file_stem}.txt"

        exporters.build_epub(meta, chapters, epub_path, session)
        exporters.save_txt(meta, chapters, txt_path)

        print("[*] 下载完成!")
        print(f"[*] EPUB: {epub_path.resolve()}")
        print(f"[*] TXT : {txt_path.resolve()}")
        print(f"[*] 成功: {len(chapters)} 章")
        print(f"[*] 失败: {len(failed_chapters)} 章")

    def _download_finished(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self._stop_event.is_set():
            self._set_status("已停止")
        else:
            self._set_progress(1.0)
            self._set_status("下载完成")


def run_gui():
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = NovalPieApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
