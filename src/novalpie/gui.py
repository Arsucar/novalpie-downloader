# coding=utf-8
"""NovalPie GUI - 基于 customtkinter 的现代化图形界面"""

from __future__ import annotations

import io
import sys
import threading
import time
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


# ── 色彩常量 ────────────────────────────────────────────────

class Colors:
    PRIMARY = "#2B87E3"
    PRIMARY_HOVER = "#1E6CB8"
    SUCCESS = "#27AE60"
    SUCCESS_HOVER = "#1E8449"
    WARNING = "#F39C12"
    WARNING_HOVER = "#D68910"
    DANGER = "#E74C3C"
    DANGER_HOVER = "#C0392B"
    CARD_LIGHT = "gray95"
    CARD_DARK = "gray17"
    CARD_BORDER_LIGHT = "gray85"
    CARD_BORDER_DARK = "gray28"


# ── 日志重定向 ──────────────────────────────────────────────

class TextHandler(io.TextIOBase):
    """将 write 调用转发到 GUI 日志区域"""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def write(self, text: str) -> int:
        if not text:
            return 0
        self.callback(text)
        return len(text)

    def flush(self):
        pass


# ── 主应用 ──────────────────────────────────────────────────

class NovalPieApp(ctk.CTk):
    # 默认字体大小
    DEFAULT_FONT_SIZE = 20
    FONT_SIZE_MIN = 15
    FONT_SIZE_MAX = 30

    def __init__(self):
        super().__init__()
        self.title("NovalPie 小说下载器")
        self.geometry("820x750")
        self.minsize(720, 620)

        self._stop_event = threading.Event()
        self._running = False
        self._font_size = self.DEFAULT_FONT_SIZE

        # 收集所有需要随字体大小变化的控件
        self._font_widgets: list[tuple] = []  # (widget, type, extra)

        self._build_ui()

    # ── 字体辅助 ────────────────────────────────────────────

    def _font(self, size_offset: int = 0, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(size=self._font_size + size_offset, weight=weight)

    def _register_font(self, widget, wtype: str, extra: dict | None = None):
        """注册控件以便字体大小变化时批量更新"""
        self._font_widgets.append((widget, wtype, extra or {}))

    def _apply_font_size(self, size: int):
        """动态更新所有注册控件的字体"""
        self._font_size = size
        for widget, wtype, extra in self._font_widgets:
            try:
                offset = extra.get("offset", 0)
                weight = extra.get("weight", "normal")
                new_font = ctk.CTkFont(size=size + offset, weight=weight)
                if wtype == "label":
                    widget.configure(font=new_font)
                elif wtype == "entry":
                    widget.configure(font=new_font)
                elif wtype == "button":
                    widget.configure(font=new_font)
                elif wtype == "textbox":
                    widget.configure(font=ctk.CTkFont(
                        family=extra.get("family", "Consolas"),
                        size=size + extra.get("offset", -2),
                    ))
                elif wtype == "checkbox":
                    widget.configure(font=new_font)
                elif wtype == "switch":
                    widget.configure(font=new_font)
                elif wtype == "slider_label":
                    widget.configure(font=new_font, text=f"字体大小: {size}")
            except Exception:
                pass

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        # 主容器
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)   # Tabview 区域可扩展
        self.grid_rowconfigure(2, weight=0)   # 底部栏固定

        # ========== 顶部标题栏 ==========
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 5))
        top_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            top_frame,
            text="NovalPie 小说下载器",
            font=self._font(8, "bold"),
            text_color=Colors.PRIMARY,
        )
        title_label.grid(row=0, column=0, sticky="w")
        self._register_font(title_label, "label", {"offset": 8, "weight": "bold"})

        subtitle_label = ctk.CTkLabel(
            top_frame,
            text="轻松下载你喜爱的小说",
            font=self._font(-2),
            text_color="gray60",
        )
        subtitle_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._register_font(subtitle_label, "label", {"offset": -2})

        # 字体大小控制
        font_ctrl = ctk.CTkFrame(top_frame, fg_color="transparent")
        font_ctrl.grid(row=0, column=2, sticky="e")

        self.label_font_size = ctk.CTkLabel(
            font_ctrl,
            text=f"字体大小: {self._font_size}",
            font=self._font(-2),
            width=110,
        )
        self.label_font_size.pack(side="left", padx=(0, 6))
        self._register_font(self.label_font_size, "slider_label", {"offset": -2})

        self.slider_font = ctk.CTkSlider(
            font_ctrl,
            from_=self.FONT_SIZE_MIN,
            to=self.FONT_SIZE_MAX,
            number_of_steps=14,
            width=120,
            command=self._on_font_size_change,
        )
        self.slider_font.set(self._font_size)
        self.slider_font.pack(side="left")

        # ========== Tabview (设置页 + 日志页) ==========
        self.tabview = ctk.CTkTabview(
            self, corner_radius=12,
            fg_color=(Colors.CARD_LIGHT, Colors.CARD_DARK),
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(5, 5))

        self.tabview.add("设置")
        self.tabview.add("日志")

        # ----- 设置标签页内容 -----
        settings_tab = self.tabview.tab("设置")
        settings_tab.grid_columnconfigure(0, weight=1)
        settings_tab.grid_rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(
            settings_tab, corner_radius=0, fg_color="transparent",
        )
        scroll_frame.grid(row=0, column=0, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

        # ── 基本设置卡片 ──
        basic_card = self._create_card(scroll_frame, "基本设置", "🔗")
        basic_card.grid_columnconfigure(0, weight=1)

        self.entry_book_url = self._create_input_group(
            basic_card, "书籍章节链接 (bookURL)", config.bookURL,
            placeholder="https://...", required=True,
        )
        self.entry_base_url = self._create_input_group(
            basic_card, "站点根地址 (base_url)", config.base_url,
            placeholder="https://...",
        )
        self.entry_cookie = self._create_input_group(
            basic_card, "Cookie 文件路径", config.cookieFilePath,
            placeholder="cookie.txt",
        )

        # ── 下载设置卡片 ──
        dl_card = self._create_card(scroll_frame, "下载设置", "⚙️")
        dl_card.grid_columnconfigure((0, 1), weight=1)

        # 预设方案按钮
        preset_frame = ctk.CTkFrame(dl_card, fg_color="transparent")
        preset_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 5))
        preset_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            preset_frame, text="预设方案:",
            font=self._font(-1),
            text_color=("gray50", "gray60"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 5))

        btn_conservative = ctk.CTkButton(
            preset_frame, text="保守", height=28, corner_radius=6,
            font=self._font(-2),
            fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            command=self._apply_preset_conservative,
        )
        btn_conservative.grid(row=0, column=1, padx=2)
        self._register_font(btn_conservative, "button", {"offset": -2})

        btn_balanced = ctk.CTkButton(
            preset_frame, text="均衡", height=28, corner_radius=6,
            font=self._font(-2),
            fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            command=self._apply_preset_balanced,
        )
        btn_balanced.grid(row=0, column=2, padx=2)
        self._register_font(btn_balanced, "button", {"offset": -2})

        btn_aggressive = ctk.CTkButton(
            preset_frame, text="激进", height=28, corner_radius=6,
            font=self._font(-2),
            fg_color=Colors.WARNING, hover_color=Colors.WARNING_HOVER,
            command=self._apply_preset_aggressive,
        )
        btn_aggressive.grid(row=0, column=3, padx=2)
        self._register_font(btn_aggressive, "button", {"offset": -2})

        # 输入行
        self.entry_delay_min = self._create_inline_input(
            dl_card, "章节间隔(秒) 最小", str(config.chapterDelayMinSec), row=1, col=0,
        )
        self.entry_delay_max = self._create_inline_input(
            dl_card, "最大", str(config.chapterDelayMaxSec), row=1, col=1,
        )
        self.entry_timeout = self._create_inline_input(
            dl_card, "章节超时(秒)", str(config.chapterReadyTimeoutSec), row=2, col=0,
        )
        self.entry_retry = self._create_inline_input(
            dl_card, "重试次数", str(config.retryPerChapter), row=2, col=1,
        )
        self.entry_max_chapters = self._create_inline_input(
            dl_card, "最大章节数 (0=不限)", str(config.maxChapters), row=3, col=0,
        )
        self.entry_first_wait = self._create_inline_input(
            dl_card, "首章额外等待(秒)", str(config.firstChapterExtraWaitSec), row=3, col=1,
        )

        # ── 选项卡片 ──
        opt_card = self._create_card(scroll_frame, "选项", "🎛️")
        opt_card.grid_columnconfigure((0, 1), weight=1)

        self.var_headless = ctk.BooleanVar(value=config.headless)
        self._create_switch(opt_card, "无头模式 (headless)", self.var_headless, row=0, col=0)

        self.var_from_current = ctk.BooleanVar(value=config.startFromCurrentChapter)
        self._create_switch(opt_card, "从当前章节开始", self.var_from_current, row=0, col=1)

        self.var_keep_failed = ctk.BooleanVar(value=config.keepFailedChapterPlaceholder)
        self._create_switch(opt_card, "保留失败章节占位", self.var_keep_failed, row=1, col=0)

        # ── 输出目录卡片 ──
        out_card = self._create_card(scroll_frame, "输出目录", "📁")
        out_card.grid_columnconfigure(0, weight=1)

        self.entry_epub_dir = self._create_input_group(
            out_card, "EPUB 输出目录", config.epubOutputDir,
        )
        self.entry_txt_dir = self._create_input_group(
            out_card, "TXT 输出目录", config.txtOutputDir,
        )
        self.entry_cache_dir = self._create_input_group(
            out_card, "缓存目录", config.cacheOutputDir,
        )

        # ----- 日志标签页内容 -----
        log_tab = self.tabview.tab("日志")
        log_tab.grid_columnconfigure(0, weight=1)
        log_tab.grid_rowconfigure(0, weight=1)

        self.text_log = ctk.CTkTextbox(
            log_tab, corner_radius=8, border_width=0,
            fg_color=("gray90", "gray13"),
            font=ctk.CTkFont(family="Consolas", size=self._font_size - 2),
        )
        self.text_log.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        self._register_font(self.text_log, "textbox", {"family": "Consolas", "offset": -2})

        # ========== 底部固定栏（进度条 + 按钮） ==========
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 15))
        bottom_frame.grid_columnconfigure(0, weight=1)

        # 进度卡片
        progress_card = ctk.CTkFrame(
            bottom_frame, corner_radius=12,
            fg_color=(Colors.CARD_LIGHT, Colors.CARD_DARK),
            border_width=1,
            border_color=(Colors.CARD_BORDER_LIGHT, Colors.CARD_BORDER_DARK),
        )
        progress_card.pack(fill="x", pady=(0, 8))

        progress_inner = ctk.CTkFrame(progress_card, fg_color="transparent")
        progress_inner.pack(fill="both", padx=15, pady=10)

        self.progress_bar = ctk.CTkProgressBar(
            progress_inner, height=8, corner_radius=4,
            progress_color=Colors.PRIMARY,
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        self.label_status = ctk.CTkLabel(
            progress_inner, text="就绪",
            font=self._font(-2),
            text_color=("gray40", "gray70"),
        )
        self.label_status.pack(anchor="w")
        self._register_font(self.label_status, "label", {"offset": -2})

        # 按钮栏
        btn_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        btn_inner = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_inner.pack()

        self.btn_start = ctk.CTkButton(
            btn_inner, text="开始下载",
            font=self._font(1, "bold"),
            height=42, corner_radius=10,
            fg_color=Colors.SUCCESS, hover_color=Colors.SUCCESS_HOVER,
            command=self._on_start,
        )
        self.btn_start.pack(side="left", padx=(0, 10))
        self._register_font(self.btn_start, "button", {"offset": 1, "weight": "bold"})

        self.btn_stop = ctk.CTkButton(
            btn_inner, text="停止",
            font=self._font(1, "bold"),
            height=42, corner_radius=10,
            fg_color=Colors.DANGER, hover_color=Colors.DANGER_HOVER,
            command=self._on_stop, state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(0, 10))
        self._register_font(self.btn_stop, "button", {"offset": 1, "weight": "bold"})

        self.btn_clear = ctk.CTkButton(
            btn_inner, text="清空日志",
            font=self._font(),
            height=42, corner_radius=10,
            fg_color="transparent", border_width=2, border_color="gray50",
            text_color=("gray30", "gray80"),
            hover_color=("gray90", "gray25"),
            command=self._on_clear_log,
        )
        self.btn_clear.pack(side="left")
        self._register_font(self.btn_clear, "button", {"offset": 0})

    # ── 卡片/控件工厂方法 ───────────────────────────────────

    def _create_card(self, parent, title: str, icon: str = "") -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent, corner_radius=15,
            fg_color=(Colors.CARD_LIGHT, Colors.CARD_DARK),
            border_width=1,
            border_color=(Colors.CARD_BORDER_LIGHT, Colors.CARD_BORDER_DARK),
        )
        card.pack(fill="x", pady=(0, 10))

        header = ctk.CTkFrame(card, fg_color="transparent", height=35)
        header.pack(fill="x", padx=15, pady=(12, 0))
        header.pack_propagate(False)

        header_label = ctk.CTkLabel(
            header,
            text=f"{icon} {title}" if icon else title,
            font=self._font(1, "bold"),
            text_color=("gray20", "gray90"),
        )
        header_label.pack(side="left")
        self._register_font(header_label, "label", {"offset": 1, "weight": "bold"})

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="x", padx=15, pady=(8, 15))

        return content

    def _create_input_group(
        self, parent, label: str, default: str = "",
        placeholder: str = "", required: bool = False,
    ) -> ctk.CTkEntry:
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(fill="x", pady=4)

        label_frame = ctk.CTkFrame(group, fg_color="transparent")
        label_frame.pack(fill="x")

        label_text = f"{label} {'*' if required else ''}"
        lbl = ctk.CTkLabel(
            label_frame, text=label_text,
            font=self._font(-2),
            text_color=("gray40", "gray70"),
        )
        lbl.pack(side="left")
        self._register_font(lbl, "label", {"offset": -2})

        if required:
            req_lbl = ctk.CTkLabel(
                label_frame, text="(必填)",
                font=self._font(-4),
                text_color="red",
            )
            req_lbl.pack(side="left", padx=(5, 0))
            self._register_font(req_lbl, "label", {"offset": -4})

        entry = ctk.CTkEntry(
            group, placeholder_text=placeholder,
            height=36, corner_radius=8, border_width=1,
            fg_color=("gray97", "gray20"),
            border_color=("gray70", "gray50"),
            font=self._font(-2),
        )
        entry.pack(fill="x", pady=(4, 0))
        entry.insert(0, default)
        self._register_font(entry, "entry", {"offset": -2})

        return entry

    def _create_inline_input(
        self, parent, label: str, default: str, row: int, col: int,
    ) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 10, 0 if col == 1 else 10), pady=5)
        frame.grid_columnconfigure(0, weight=1)

        if label:
            lbl = ctk.CTkLabel(
                frame, text=label,
                font=self._font(-2),
                text_color=("gray40", "gray70"),
            )
            lbl.pack(anchor="w", pady=(0, 2))
            self._register_font(lbl, "label", {"offset": -2})

        entry = ctk.CTkEntry(
            frame, height=34, corner_radius=8, border_width=1,
            fg_color=("gray97", "gray20"),
            border_color=("gray70", "gray50"),
            font=self._font(-2),
        )
        entry.pack(fill="x")
        entry.insert(0, str(default))
        self._register_font(entry, "entry", {"offset": -2})

        return entry

    def _create_switch(self, parent, text: str, variable, row: int, col: int):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=col, sticky="w", padx=(0, 20), pady=5)

        sw = ctk.CTkSwitch(
            frame, text=text, variable=variable,
            font=self._font(-1),
            progress_color=Colors.PRIMARY,
        )
        sw.pack(side="left")
        self._register_font(sw, "switch", {"offset": -1})

        return sw

    # ── 预设方案 ────────────────────────────────────────────

    def _apply_preset(self, delay_min: float, delay_max: float, timeout: float, retry: int, first_wait: float):
        if not hasattr(self, 'entry_delay_min'):
            return
        self.entry_delay_min.delete(0, "end")
        self.entry_delay_min.insert(0, str(delay_min))
        self.entry_delay_max.delete(0, "end")
        self.entry_delay_max.insert(0, str(delay_max))
        self.entry_timeout.delete(0, "end")
        self.entry_timeout.insert(0, str(timeout))
        self.entry_retry.delete(0, "end")
        self.entry_retry.insert(0, str(retry))
        self.entry_first_wait.delete(0, "end")
        self.entry_first_wait.insert(0, str(first_wait))

    def _apply_preset_conservative(self):
        """保守：间隔 1.0~1.5s，超时 20s，重试 2 次，首章 3s"""
        self._apply_preset(1.0, 1.5, 20, 2, 3)
        self._log("[*] 已应用预设: 保守\n")

    def _apply_preset_balanced(self):
        """均衡：间隔 0.8~1.2s，超时 15s，重试 2 次，首章 2s"""
        self._apply_preset(0.8, 1.2, 15, 2, 2)
        self._log("[*] 已应用预设: 均衡\n")

    def _apply_preset_aggressive(self):
        """激进：间隔 0.5~1.0s，超时 15s，重试 1 次，首章 1s"""
        self._apply_preset(0.5, 1.0, 15, 1, 1)
        self._log("[*] 已应用预设: 激进（注意封号风险）\n")

    # ── 字体大小滑块回调 ────────────────────────────────────

    def _on_font_size_change(self, value):
        size = int(round(value))
        if size != self._font_size:
            self._apply_font_size(size)

    # ── 配置读写 ────────────────────────────────────────────

    def _apply_ui_to_config(self) -> list[str]:
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
        parsed_base = urlparse(config.base_url)
        parsed_book = urlparse(config.bookURL)
        if parsed_base.scheme != parsed_book.scheme or parsed_base.netloc != parsed_book.netloc:
            print("[x] base_url 和 bookURL 域名不一致")
            return

        cookie_line = utils.read_cookie_line(config.cookieFilePath)
        auth_token = utils.read_auth_token(config.cookieFilePath)
        if cookie_line:
            print("[*] Cookie 已加载")
        if auth_token:
            print("[*] JWT Token 已加载")
        if not cookie_line and not auth_token:
            print("[*] 未找到认证信息，继续无认证模式")

        try:
            book_id, start_chapter_id = network.parse_book_url(config.bookURL)
        except Exception as e:
            print(f"[x] 无效的 bookURL: {e}")
            return

        session = network.make_session(cookie_line, auth_token=auth_token)

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

        # 计时器
        _t_start = time.monotonic()
        _t_last = _t_start

        def _format_duration(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            if h > 0:
                return f"{h}h{m:02d}m{s:02d}s"
            elif m > 0:
                return f"{m}m{s:02d}s"
            return f"{s}s"

        def _update_stats(current: int, total: int):
            nonlocal _t_last
            now = time.monotonic()
            elapsed = now - _t_start
            interval = now - _t_last

            if interval > 0:
                rate_ch = current / elapsed  # 章节/秒
                eta = (total - current) / rate_ch if rate_ch > 0 else 0
                status = (
                    f"下载中 ({current}/{total}) | "
                    f"耗时 {_format_duration(elapsed)} | "
                    f"速率 {rate_ch:.2f}章/s | "
                    f"预计剩余 {_format_duration(eta)}"
                )
            else:
                status = f"下载中 ({current}/{total})"
            self._set_status(status)
            self._set_progress(current / total if total > 0 else 0)
            _t_last = now

        # Monkey-patch print_progress 以更新进度条和统计
        _orig_print_progress = utils.print_progress
        def _gui_print_progress(current: int, total: int, title: str):
            _orig_print_progress(current, total, title)
            _update_stats(current, total)
        utils.print_progress = _gui_print_progress

        # Monkey-patch sleep_between 以支持停止
        _orig_sleep = utils.sleep_between
        def _checkable_sleep(min_sec: float, max_sec: float):
            import random, time
            delay = max(min_sec, min(max_sec, random.uniform(min_sec, max_sec)))
            step = 0.2
            elapsed = 0.0
            while elapsed < delay:
                if self._stop_event.is_set():
                    return
                s = min(step, delay - elapsed)
                time.sleep(s)
                elapsed += s
        utils.sleep_between = _checkable_sleep

        # Monkey-patch wait_for_chapter_text 以支持停止
        _orig_wait = browser.wait_for_chapter_text
        def _checkable_wait(page, timeout_sec, current_title="", next_title=""):
            import time as _t
            deadline = _t.monotonic() + timeout_sec
            while _t.monotonic() < deadline:
                if self._stop_event.is_set():
                    raise KeyboardInterrupt("用户请求停止")
                try:
                    return _orig_wait(page, min(timeout_sec, 2.0), current_title, next_title)
                except Exception:
                    if self._stop_event.is_set():
                        raise KeyboardInterrupt("用户请求停止")
                    remaining = deadline - _t.monotonic()
                    if remaining <= 0:
                        raise
                    _t.sleep(min(0.5, remaining))
        browser.wait_for_chapter_text = _checkable_wait

        try:
            chapters, failed_chapters, chapter_cache = browser.download_chapters_with_browser(
                chapter_refs, cookie_line, chapter_cache, auth_token=auth_token, book_id=book_id
            )
        finally:
            utils.print_progress = _orig_print_progress
            utils.sleep_between = _orig_sleep
            browser.wait_for_chapter_text = _orig_wait

        # 打印下载统计
        _t_end = time.monotonic()
        _total_elapsed = _t_end - _t_start
        _total_chars = sum(len(ch.text) for ch in chapters)
        print(f"\n{'='*50}")
        print(f"[*] 下载统计")
        print(f"    总耗时: {_format_duration(_total_elapsed)}")
        print(f"    成功: {len(chapters)} 章")
        print(f"    失败: {len(failed_chapters)} 章")
        print(f"    总字符: {_total_chars:,}")
        if _total_elapsed > 0:
            print(f"    平均速率: {len(chapters) / _total_elapsed:.2f} 章/秒")
            print(f"    字符速率: {_total_chars / _total_elapsed:.0f} 字符/秒")
        print(f"{'='*50}\n")

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
