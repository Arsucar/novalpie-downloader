# coding=utf-8
"""NovalPie GUI - 基于 customtkinter 的现代化图形界面 + 任务队列"""

from __future__ import annotations

import io
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
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


# ── 任务状态枚举 ────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "等待中"
    RUNNING = "下载中"
    DONE = "已完成"
    FAILED = "失败"
    STOPPED = "已停止"


# ── 下载任务（独立配置 + 独立缓存） ─────────────────────────

@dataclass
class DownloadTask:
    """单个下载任务，封装所有独立配置和运行时状态"""
    # 标识
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # 输入配置（快照，不依赖全局 config）
    book_url: str = ""
    base_url: str = ""
    cookie_path: str = ""
    delay_min: float = 2.0
    delay_max: float = 3.0
    timeout: float = 35.0
    retry: int = 4
    max_chapters: int = 0
    first_wait: float = 10.0
    headless: bool = True
    start_from_current: bool = True
    keep_failed: bool = True
    epub_dir: str = "./epubBooks_novalpie"
    txt_dir: str = "./txtBooks_novalpie"
    cache_dir: str = "./cache_novalpie"

    # 运行时状态（任务专属，不共享）
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    status_text: str = "等待中"
    book_title: str = ""
    total_chapters: int = 0
    downloaded_chapters: int = 0

    # 运行时数据（任务完成后释放）
    _chapter_cache: Optional[dict] = field(default=None, repr=False)
    _chapters_result: Optional[list] = field(default=None, repr=False)
    _failed_chapters: Optional[list] = field(default=None, repr=False)

    def memory_footprint_mb(self) -> float:
        """估算当前内存占用（MB）"""
        size = 0
        if self._chapter_cache:
            for ch in self._chapter_cache.values():
                if hasattr(ch, 'text'):
                    size += len(ch.text) * 2  # UTF-16 approx
        if self._chapters_result:
            for ch in self._chapters_result:
                if hasattr(ch, 'text'):
                    size += len(ch.text) * 2
        return size / (1024 * 1024)

    def release_memory(self):
        """释放任务运行时数据，保留磁盘缓存"""
        self._chapter_cache = None
        self._chapters_result = None
        self._failed_chapters = None


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
    DEFAULT_FONT_SIZE = 20
    FONT_SIZE_MIN = 15
    FONT_SIZE_MAX = 30

    def __init__(self):
        super().__init__()
        self.title("NovalPie 小说下载器")
        self.geometry("900x800")
        self.minsize(780, 650)

        self._stop_event = threading.Event()
        self._running = False
        self._font_size = self.DEFAULT_FONT_SIZE
        self._font_widgets: list[tuple] = []

        # 任务队列
        self._task_queue: list[DownloadTask] = []
        self._queue_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

        self._build_ui()

    # ── 字体辅助 ────────────────────────────────────────────

    def _font(self, size_offset: int = 0, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(size=self._font_size + size_offset, weight=weight)

    def _register_font(self, widget, wtype: str, extra: dict | None = None):
        self._font_widgets.append((widget, wtype, extra or {}))

    def _apply_font_size(self, size: int):
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
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        # ========== 顶部标题栏 ==========
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 5))
        top_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            top_frame, text="NovalPie 小说下载器",
            font=self._font(8, "bold"), text_color=Colors.PRIMARY,
        )
        title_label.grid(row=0, column=0, sticky="w")
        self._register_font(title_label, "label", {"offset": 8, "weight": "bold"})

        subtitle_label = ctk.CTkLabel(
            top_frame, text="轻松下载你喜爱的小说",
            font=self._font(-2), text_color="gray60",
        )
        subtitle_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._register_font(subtitle_label, "label", {"offset": -2})

        font_ctrl = ctk.CTkFrame(top_frame, fg_color="transparent")
        font_ctrl.grid(row=0, column=2, sticky="e")

        self.label_font_size = ctk.CTkLabel(
            font_ctrl, text=f"字体大小: {self._font_size}",
            font=self._font(-2), width=110,
        )
        self.label_font_size.pack(side="left", padx=(0, 6))
        self._register_font(self.label_font_size, "slider_label", {"offset": -2})

        self.slider_font = ctk.CTkSlider(
            font_ctrl, from_=self.FONT_SIZE_MIN, to=self.FONT_SIZE_MAX,
            number_of_steps=14, width=120, command=self._on_font_size_change,
        )
        self.slider_font.set(self._font_size)
        self.slider_font.pack(side="left")

        # ========== Tabview (设置 + 任务队列 + 日志) ==========
        self.tabview = ctk.CTkTabview(
            self, corner_radius=12,
            fg_color=(Colors.CARD_LIGHT, Colors.CARD_DARK),
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(5, 5))

        self.tabview.add("设置")
        self.tabview.add("任务队列")
        self.tabview.add("日志")

        self._build_settings_tab()
        self._build_queue_tab()
        self._build_log_tab()

        # ========== 底部固定栏 ==========
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 15))
        bottom_frame.grid_columnconfigure(0, weight=1)

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
            progress_inner, height=8, corner_radius=4, progress_color=Colors.PRIMARY,
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        self.label_status = ctk.CTkLabel(
            progress_inner, text="就绪",
            font=self._font(-2), text_color=("gray40", "gray70"),
        )
        self.label_status.pack(anchor="w")
        self._register_font(self.label_status, "label", {"offset": -2})

        btn_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        btn_inner = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_inner.pack()

        self.btn_start = ctk.CTkButton(
            btn_inner, text="开始下载",
            font=self._font(1, "bold"), height=42, corner_radius=10,
            fg_color=Colors.SUCCESS, hover_color=Colors.SUCCESS_HOVER,
            command=self._on_start,
        )
        self.btn_start.pack(side="left", padx=(0, 10))
        self._register_font(self.btn_start, "button", {"offset": 1, "weight": "bold"})

        self.btn_stop = ctk.CTkButton(
            btn_inner, text="停止",
            font=self._font(1, "bold"), height=42, corner_radius=10,
            fg_color=Colors.DANGER, hover_color=Colors.DANGER_HOVER,
            command=self._on_stop, state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(0, 10))
        self._register_font(self.btn_stop, "button", {"offset": 1, "weight": "bold"})

        self.btn_clear = ctk.CTkButton(
            btn_inner, text="清空日志",
            font=self._font(), height=42, corner_radius=10,
            fg_color="transparent", border_width=2, border_color="gray50",
            text_color=("gray30", "gray80"), hover_color=("gray90", "gray25"),
            command=self._on_clear_log,
        )
        self.btn_clear.pack(side="left")
        self._register_font(self.btn_clear, "button", {"offset": 0})

    # ── 设置标签页 ──────────────────────────────────────────

    def _build_settings_tab(self):
        settings_tab = self.tabview.tab("设置")
        settings_tab.grid_columnconfigure(0, weight=1)
        settings_tab.grid_rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(
            settings_tab, corner_radius=0, fg_color="transparent",
        )
        scroll_frame.grid(row=0, column=0, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

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

        dl_card = self._create_card(scroll_frame, "下载设置", "⚙️")
        dl_card.grid_columnconfigure((0, 1), weight=1)

        preset_frame = ctk.CTkFrame(dl_card, fg_color="transparent")
        preset_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 5))
        preset_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            preset_frame, text="预设方案:",
            font=self._font(-1), text_color=("gray50", "gray60"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 5))

        btn_conservative = ctk.CTkButton(
            preset_frame, text="保守", height=28, corner_radius=6,
            font=self._font(-2), fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            command=self._apply_preset_conservative,
        )
        btn_conservative.grid(row=0, column=1, padx=2)
        self._register_font(btn_conservative, "button", {"offset": -2})

        btn_balanced = ctk.CTkButton(
            preset_frame, text="均衡", height=28, corner_radius=6,
            font=self._font(-2), fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            command=self._apply_preset_balanced,
        )
        btn_balanced.grid(row=0, column=2, padx=2)
        self._register_font(btn_balanced, "button", {"offset": -2})

        btn_aggressive = ctk.CTkButton(
            preset_frame, text="激进", height=28, corner_radius=6,
            font=self._font(-2), fg_color=Colors.WARNING, hover_color=Colors.WARNING_HOVER,
            command=self._apply_preset_aggressive,
        )
        btn_aggressive.grid(row=0, column=3, padx=2)
        self._register_font(btn_aggressive, "button", {"offset": -2})

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

        opt_card = self._create_card(scroll_frame, "选项", "🎛️")
        opt_card.grid_columnconfigure((0, 1), weight=1)

        self.var_headless = ctk.BooleanVar(value=config.headless)
        self._create_switch(opt_card, "无头模式 (headless)", self.var_headless, row=0, col=0)

        self.var_from_current = ctk.BooleanVar(value=config.startFromCurrentChapter)
        self._create_switch(opt_card, "从当前章节开始", self.var_from_current, row=0, col=1)

        self.var_keep_failed = ctk.BooleanVar(value=config.keepFailedChapterPlaceholder)
        self._create_switch(opt_card, "保留失败章节占位", self.var_keep_failed, row=1, col=0)

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

    # ── 任务队列标签页 ──────────────────────────────────────

    def _build_queue_tab(self):
        queue_tab = self.tabview.tab("任务队列")
        queue_tab.grid_columnconfigure(0, weight=1)
        queue_tab.grid_rowconfigure(0, weight=1)

        # 任务列表
        self.queue_frame = ctk.CTkScrollableFrame(
            queue_tab, corner_radius=0, fg_color="transparent",
        )
        self.queue_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=(15, 5))
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # 空状态提示
        self.label_queue_empty = ctk.CTkLabel(
            queue_tab, text="暂无任务，请在设置页填写链接后点击「添加到队列」",
            font=self._font(-2), text_color="gray50",
        )
        self.label_queue_empty.grid(row=0, column=0, sticky="n")
        self._register_font(self.label_queue_empty, "label", {"offset": -2})

        # 底部操作栏
        queue_bottom = ctk.CTkFrame(queue_tab, fg_color="transparent")
        queue_bottom.grid(row=1, column=0, sticky="ew", padx=15, pady=(5, 15))
        queue_bottom.grid_columnconfigure(0, weight=1)

        info_frame = ctk.CTkFrame(queue_bottom, fg_color="transparent")
        info_frame.grid(row=0, column=0, sticky="w")

        self.label_queue_info = ctk.CTkLabel(
            info_frame, text="队列: 0 个任务",
            font=self._font(-3), text_color="gray50",
        )
        self.label_queue_info.pack(side="left")
        self._register_font(self.label_queue_info, "label", {"offset": -3})

        btn_frame = ctk.CTkFrame(queue_bottom, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        self.btn_add_queue = ctk.CTkButton(
            btn_frame, text="添加到队列", height=32, corner_radius=8,
            font=self._font(-2), fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            command=self._on_add_to_queue,
        )
        self.btn_add_queue.pack(side="left", padx=(0, 8))
        self._register_font(self.btn_add_queue, "button", {"offset": -2})

        self.btn_remove_selected = ctk.CTkButton(
            btn_frame, text="删除选中", height=32, corner_radius=8,
            font=self._font(-2), fg_color=Colors.DANGER, hover_color=Colors.DANGER_HOVER,
            command=self._on_remove_selected, state="disabled",
        )
        self.btn_remove_selected.pack(side="left", padx=(0, 8))
        self._register_font(self.btn_remove_selected, "button", {"offset": -2})

        self.btn_clear_done = ctk.CTkButton(
            btn_frame, text="清除已完成", height=32, corner_radius=8,
            font=self._font(-2), fg_color="gray50", hover_color="gray40",
            command=self._on_clear_done,
        )
        self.btn_clear_done.pack(side="left")
        self._register_font(self.btn_clear_done, "button", {"offset": -2})

        self._queue_widgets: dict[str, dict] = {}  # task_id -> widgets

    # ── 日志标签页 ──────────────────────────────────────────

    def _build_log_tab(self):
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
            header, text=f"{icon} {title}" if icon else title,
            font=self._font(1, "bold"), text_color=("gray20", "gray90"),
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
            font=self._font(-2), text_color=("gray40", "gray70"),
        )
        lbl.pack(side="left")
        self._register_font(lbl, "label", {"offset": -2})

        if required:
            req_lbl = ctk.CTkLabel(
                label_frame, text="(必填)",
                font=self._font(-4), text_color="red",
            )
            req_lbl.pack(side="left", padx=(5, 0))
            self._register_font(req_lbl, "label", {"offset": -4})

        entry = ctk.CTkEntry(
            group, placeholder_text=placeholder, height=36, corner_radius=8,
            border_width=1, fg_color=("gray97", "gray20"),
            border_color=("gray70", "gray50"), font=self._font(-2),
        )
        entry.pack(fill="x", pady=(4, 0))
        entry.insert(0, default)
        self._register_font(entry, "entry", {"offset": -2})

        return entry

    def _create_inline_input(
        self, parent, label: str, default: str, row: int, col: int,
    ) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=col, sticky="ew",
                   padx=(0 if col == 0 else 10, 0 if col == 1 else 10), pady=5)
        frame.grid_columnconfigure(0, weight=1)

        if label:
            lbl = ctk.CTkLabel(
                frame, text=label, font=self._font(-2),
                text_color=("gray40", "gray70"),
            )
            lbl.pack(anchor="w", pady=(0, 2))
            self._register_font(lbl, "label", {"offset": -2})

        entry = ctk.CTkEntry(
            frame, height=34, corner_radius=8, border_width=1,
            fg_color=("gray97", "gray20"), border_color=("gray70", "gray50"),
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
            font=self._font(-1), progress_color=Colors.PRIMARY,
        )
        sw.pack(side="left")
        self._register_font(sw, "switch", {"offset": -1})

        return sw

    # ── 预设方案 ────────────────────────────────────────────

    def _apply_preset(self, delay_min, delay_max, timeout, retry, first_wait):
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
        self._apply_preset(1.0, 1.5, 20, 2, 3)
        self._log("[*] 已应用预设: 保守\n")

    def _apply_preset_balanced(self):
        self._apply_preset(0.8, 1.2, 15, 2, 2)
        self._log("[*] 已应用预设: 均衡\n")

    def _apply_preset_aggressive(self):
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

    def _snapshot_task_from_ui(self) -> DownloadTask:
        """从当前 UI 快照创建一个独立的任务配置"""
        return DownloadTask(
            book_url=self.entry_book_url.get().strip(),
            base_url=self.entry_base_url.get().strip(),
            cookie_path=self.entry_cookie.get().strip(),
            delay_min=float(self.entry_delay_min.get().strip() or "2.0"),
            delay_max=float(self.entry_delay_max.get().strip() or "3.0"),
            timeout=float(self.entry_timeout.get().strip() or "35.0"),
            retry=int(self.entry_retry.get().strip() or "4"),
            max_chapters=int(self.entry_max_chapters.get().strip() or "0"),
            first_wait=float(self.entry_first_wait.get().strip() or "10.0"),
            headless=self.var_headless.get(),
            start_from_current=self.var_from_current.get(),
            keep_failed=self.var_keep_failed.get(),
            epub_dir=self.entry_epub_dir.get().strip(),
            txt_dir=self.entry_txt_dir.get().strip(),
            cache_dir=self.entry_cache_dir.get().strip(),
        )

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

    # ── 任务队列管理 ────────────────────────────────────────

    def _on_add_to_queue(self):
        errors = self._apply_ui_to_config()
        if errors:
            self._log("\n".join(f"[x] {e}" for e in errors) + "\n")
            return
        if not config.bookURL:
            self._log("[x] 请填写书籍章节链接\n")
            return

        task = self._snapshot_task_from_ui()
        task.book_title = f"任务 #{len(self._task_queue) + 1}"

        with self._queue_lock:
            self._task_queue.append(task)

        self._log(f"[+] 已添加任务到队列: {task.book_url} (ID: {task.task_id})\n")
        self._refresh_queue_ui()

    def _on_remove_selected(self):
        to_remove = [tid for tid, w in self._queue_widgets.items() if w.get("var", ctk.BooleanVar(value=False)).get()]
        if not to_remove:
            return

        with self._queue_lock:
            self._task_queue = [t for t in self._task_queue if t.task_id not in to_remove]

        for tid in to_remove:
            if tid in self._queue_widgets:
                for widget in self._queue_widgets[tid].values():
                    if hasattr(widget, 'destroy'):
                        widget.destroy()
                del self._queue_widgets[tid]

        self._log(f"[-] 已删除 {len(to_remove)} 个任务\n")
        self._refresh_queue_ui()

    def _on_clear_done(self):
        with self._queue_lock:
            done_ids = {t.task_id for t in self._task_queue if t.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.STOPPED)}
            self._task_queue = [t for t in self._task_queue if t.status not in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.STOPPED)]

        for tid in done_ids:
            if tid in self._queue_widgets:
                for widget in self._queue_widgets[tid].values():
                    if hasattr(widget, 'destroy'):
                        widget.destroy()
                del self._queue_widgets[tid]

        self._log(f"[*] 已清除 {len(done_ids)} 个已完成任务\n")
        self._refresh_queue_ui()

    def _refresh_queue_ui(self):
        """刷新任务队列 UI"""
        def _update():
            # 清除旧控件
            for tid, widgets in self._queue_widgets.items():
                for w in widgets.values():
                    if hasattr(w, 'destroy'):
                        w.destroy()
            self._queue_widgets.clear()

            # 重建
            for i, task in enumerate(self._task_queue):
                self._create_queue_item(task, i)

            # 更新空状态
            has_items = len(self._task_queue) > 0
            self.label_queue_empty.grid_remove() if has_items else self.label_queue_empty.grid()
            self.label_queue_info.configure(text=f"队列: {len(self._task_queue)} 个任务")

            # 更新按钮状态
            self.btn_remove_selected.configure(state="normal" if has_items else "disabled")

        self.after(0, _update)

    def _create_queue_item(self, task: DownloadTask, index: int):
        """创建单个任务队列项 UI"""
        item_frame = ctk.CTkFrame(
            self.queue_frame, corner_radius=10,
            fg_color=(Colors.CARD_LIGHT, Colors.CARD_DARK),
            border_width=1,
            border_color=(Colors.CARD_BORDER_LIGHT, Colors.CARD_BORDER_DARK),
        )
        item_frame.pack(fill="x", pady=4)

        var = ctk.BooleanVar(value=False)
        chk = ctk.CTkCheckBox(item_frame, text="", variable=var, width=20)
        chk.grid(row=0, column=0, padx=(10, 5), pady=8, sticky="w")

        # 状态指示
        status_colors = {
            TaskStatus.PENDING: "gray50",
            TaskStatus.RUNNING: Colors.PRIMARY,
            TaskStatus.DONE: Colors.SUCCESS,
            TaskStatus.FAILED: Colors.DANGER,
            TaskStatus.STOPPED: Colors.WARNING,
        }
        status_label = ctk.CTkLabel(
            item_frame, text=task.status.value,
            font=self._font(-4), text_color=status_colors.get(task.status, "gray50"),
            width=60,
        )
        status_label.grid(row=0, column=1, padx=5, sticky="w")

        # 书名/URL
        title_text = task.book_title or task.book_url
        if len(title_text) > 50:
            title_text = title_text[:47] + "..."
        title_label = ctk.CTkLabel(
            item_frame, text=title_text,
            font=self._font(-2), text_color=("gray20", "gray90"),
            anchor="w",
        )
        title_label.grid(row=0, column=2, padx=10, sticky="ew", fill="x")

        # 进度
        progress_label = ctk.CTkLabel(
            item_frame, text=f"0/{task.total_chapters or '?'}",
            font=self._font(-3), text_color="gray50",
            width=80,
        )
        progress_label.grid(row=0, column=3, padx=5, sticky="e")

        # 删除按钮
        del_btn = ctk.CTkButton(
            item_frame, text="×", width=28, height=28, corner_radius=6,
            font=self._font(2), fg_color="transparent",
            text_color=("gray40", "gray60"), hover_color=Colors.DANGER,
            command=lambda tid=task.task_id: self._remove_single_task(tid),
        )
        del_btn.grid(row=0, column=4, padx=(5, 10), sticky="e")

        item_frame.grid_columnconfigure(2, weight=1)

        self._queue_widgets[task.task_id] = {
            "frame": item_frame, "var": var, "status": status_label,
            "title": title_label, "progress": progress_label,
        }

    def _remove_single_task(self, task_id: str):
        with self._queue_lock:
            self._task_queue = [t for t in self._task_queue if t.task_id != task_id]
        if task_id in self._queue_widgets:
            for w in self._queue_widgets[task_id].values():
                if hasattr(w, 'destroy'):
                    w.destroy()
            del self._queue_widgets[task_id]
        self._refresh_queue_ui()

    def _update_queue_item_ui(self, task: DownloadTask):
        """更新单个任务项的 UI 显示"""
        def _update():
            if task.task_id not in self._queue_widgets:
                return
            widgets = self._queue_widgets[task.task_id]

            status_colors = {
                TaskStatus.PENDING: "gray50",
                TaskStatus.RUNNING: Colors.PRIMARY,
                TaskStatus.DONE: Colors.SUCCESS,
                TaskStatus.FAILED: Colors.DANGER,
                TaskStatus.STOPPED: Colors.WARNING,
            }
            widgets["status"].configure(
                text=task.status.value,
                text_color=status_colors.get(task.status, "gray50"),
            )
            widgets["progress"].configure(
                text=f"{task.downloaded_chapters}/{task.total_chapters or '?'}"
            )
            if task.book_title:
                title_text = task.book_title
                if len(title_text) > 50:
                    title_text = title_text[:47] + "..."
                widgets["title"].configure(text=title_text)

        self.after(0, _update)

    # ── 按钮回调 ────────────────────────────────────────────

    def _on_start(self):
        # 如果队列为空，从当前 UI 创建临时任务
        with self._queue_lock:
            has_queue = len(self._task_queue) > 0

        if not has_queue:
            errors = self._apply_ui_to_config()
            if errors:
                self._log("\n".join(f"[x] {e}" for e in errors) + "\n")
                return
            if not config.bookURL:
                self._log("[x] 请填写书籍章节链接或添加到队列\n")
                return
            task = self._snapshot_task_from_ui()
            with self._queue_lock:
                self._task_queue.append(task)
            self._refresh_queue_ui()

        self._stop_event.clear()
        self._running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_progress(0)
        self._set_status("队列执行中...")

        self._worker_thread = threading.Thread(target=self._run_queue_worker, daemon=True)
        self._worker_thread.start()

    def _on_stop(self):
        self._stop_event.set()
        self._set_status("正在停止...")
        self._log("[!] 用户请求停止\n")

    def _on_clear_log(self):
        self.text_log.delete("1.0", "end")

    # ── 队列工作线程 ────────────────────────────────────────

    def _run_queue_worker(self):
        """顺序执行任务队列"""
        while not self._stop_event.is_set():
            with self._queue_lock:
                pending = [t for t in self._task_queue if t.status == TaskStatus.PENDING]
                if not pending:
                    break
                task = pending[0]

            task.status = TaskStatus.RUNNING
            self._update_queue_item_ui(task)

            # 执行单个任务（独立配置 + 独立缓存）
            self._execute_single_task(task)

            # 任务完成后释放内存
            task.release_memory()

            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.DONE
            self._update_queue_item_ui(task)

        # 队列完成或停止
        self._running = False
        self.after(0, self._download_finished)

    def _execute_single_task(self, task: DownloadTask):
        """执行单个下载任务，使用独立配置和缓存"""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        handler = TextHandler(self._log)
        sys.stdout = handler
        sys.stderr = handler

        try:
            self._do_task(task)
        except KeyboardInterrupt:
            task.status = TaskStatus.STOPPED
            print("[!] 任务已停止")
        except Exception as e:
            task.status = TaskStatus.FAILED
            print(f"[x] 任务失败: {e}")
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    # ── 单任务下载逻辑 ──────────────────────────────────────

    def _do_task(self, task: DownloadTask):
        """执行单个任务，不依赖全局 config"""
        parsed_base = urlparse(task.base_url)
        parsed_book = urlparse(task.book_url)
        if parsed_base.scheme != parsed_book.scheme or parsed_base.netloc != parsed_book.netloc:
            print("[x] base_url 和 bookURL 域名不一致")
            return

        cookie_line = utils.read_cookie_line(task.cookie_path)
        auth_token = utils.read_auth_token(task.cookie_path)
        if cookie_line:
            print("[*] Cookie 已加载")
        if auth_token:
            print("[*] JWT Token 已加载")
        if not cookie_line and not auth_token:
            print("[*] 未找到认证信息，继续无认证模式")

        try:
            book_id, start_chapter_id = network.parse_book_url(task.book_url)
        except Exception as e:
            print(f"[x] 无效的 bookURL: {e}")
            return

        session = network.make_session(cookie_line, auth_token=auth_token)

        # 独立缓存：每个任务加载自己的缓存文件
        chapter_cache = cache.load_chapter_cache(book_id)
        task._chapter_cache = chapter_cache  # 绑定到任务
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
            chapter_refs = network.fetch_chapter_list_via_html(session, book_id, task.book_url)
            print(f"[*] 章节列表来源: HTML, 数量={len(chapter_refs)}")

        if not chapter_refs:
            print("[x] 未找到章节列表，请检查链接和 Cookie")
            return

        start_idx = utils.pick_start_index(chapter_refs, start_chapter_id, task.start_from_current)
        chapter_refs = chapter_refs[start_idx:]

        if task.max_chapters > 0:
            chapter_refs = chapter_refs[:task.max_chapters]

        if not chapter_refs:
            print("[x] 过滤后无章节可下载")
            return

        meta = network.fetch_book_meta(session, book_id, task.book_url)
        task.book_title = meta.title
        self._update_queue_item_ui(task)
        task.total_chapters = len(chapter_refs)

        print(f"[*] 书名: {meta.title}")
        if meta.author:
            print(f"[*] 作者: {meta.author}")
        print(f"[*] 待下载章节: {len(chapter_refs)}")

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

            task.downloaded_chapters = current
            self._update_queue_item_ui(task)

            if interval > 0:
                rate_ch = current / elapsed
                eta = (total - current) / rate_ch if rate_ch > 0 else 0
                status = (
                    f"[{task.book_title}] 下载中 ({current}/{total}) | "
                    f"耗时 {_format_duration(elapsed)} | "
                    f"速率 {rate_ch:.2f}章/s | "
                    f"预计剩余 {_format_duration(eta)}"
                )
            else:
                status = f"[{task.book_title}] 下载中 ({current}/{total})"
            self._set_status(status)
            self._set_progress(current / total if total > 0 else 0)
            _t_last = now

        _orig_print_progress = utils.print_progress
        def _gui_print_progress(current: int, total: int, title: str):
            _orig_print_progress(current, total, title)
            _update_stats(current, total)
        utils.print_progress = _gui_print_progress

        # Monkey-patch sleep_between 以支持停止
        _orig_sleep = utils.sleep_between
        def _checkable_sleep(min_sec: float, max_sec: float):
            import random, time as _t
            delay = max(min_sec, min(max_sec, random.uniform(min_sec, max_sec)))
            step = 0.2
            elapsed = 0.0
            while elapsed < delay:
                if self._stop_event.is_set():
                    return
                s = min(step, delay - elapsed)
                _t.sleep(s)
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

        # 使用任务独立配置覆盖全局 config（仅用于 browser 模块读取）
        _saved_config = {
            'chapterDelayMinSec': config.chapterDelayMinSec,
            'chapterDelayMaxSec': config.chapterDelayMaxSec,
            'chapterReadyTimeoutSec': config.chapterReadyTimeoutSec,
            'retryPerChapter': config.retryPerChapter,
            'firstChapterExtraWaitSec': config.firstChapterExtraWaitSec,
            'headless': config.headless,
            'keepFailedChapterPlaceholder': config.keepFailedChapterPlaceholder,
            'base_url': config.base_url,
        }
        config.chapterDelayMinSec = task.delay_min
        config.chapterDelayMaxSec = task.delay_max
        config.chapterReadyTimeoutSec = task.timeout
        config.retryPerChapter = task.retry
        config.firstChapterExtraWaitSec = task.first_wait
        config.headless = task.headless
        config.keepFailedChapterPlaceholder = task.keep_failed
        config.base_url = task.base_url

        try:
            chapters, failed_chapters, chapter_cache = browser.download_chapters_with_browser(
                chapter_refs, cookie_line, chapter_cache, auth_token=auth_token, book_id=book_id
            )
            task._chapters_result = chapters
            task._failed_chapters = failed_chapters
        finally:
            utils.print_progress = _orig_print_progress
            utils.sleep_between = _orig_sleep
            browser.wait_for_chapter_text = _orig_wait
            # 恢复全局 config
            for k, v in _saved_config.items():
                setattr(config, k, v)

        _t_end = time.monotonic()
        _total_elapsed = _t_end - _t_start
        _total_chars = sum(len(ch.text) for ch in chapters)
        print(f"\n{'='*50}")
        print(f"[*] [{meta.title}] 下载统计")
        print(f"    总耗时: {_format_duration(_total_elapsed)}")
        print(f"    成功: {len(chapters)} 章")
        print(f"    失败: {len(failed_chapters)} 章")
        print(f"    总字符: {_total_chars:,}")
        if _total_elapsed > 0:
            print(f"    平均速率: {len(chapters) / _total_elapsed:.2f} 章/秒")
            print(f"    字符速率: {_total_chars / _total_elapsed:.0f} 字符/秒")
        print(f"{'='*50}\n")

        if self._stop_event.is_set():
            task.status = TaskStatus.STOPPED
            print("[!] 下载已被用户停止")
            if chapters:
                self._save_task_output(task, meta, chapters, failed_chapters, chapter_cache, book_id, session)
            return

        if not chapters:
            task.status = TaskStatus.FAILED
            print("[x] 所有章节下载失败，无输出")
            return

        task.status = TaskStatus.DONE
        self._save_task_output(task, meta, chapters, failed_chapters, chapter_cache, book_id, session)

    def _save_task_output(self, task, meta, chapters, failed_chapters, chapter_cache, book_id, session):
        """保存任务输出，使用任务独立的输出目录"""
        # 使用任务配置中的输出目录
        _saved_dirs = {
            'epubOutputDir': config.epubOutputDir,
            'txtOutputDir': config.txtOutputDir,
            'cacheOutputDir': config.cacheOutputDir,
        }
        config.epubOutputDir = task.epub_dir
        config.txtOutputDir = task.txt_dir
        config.cacheOutputDir = task.cache_dir

        try:
            cache.save_chapter_cache(book_id, list(chapter_cache.values()))
            print(f"[*] 已缓存 {len(chapter_cache)} 个章节")

            Path(task.epub_dir).mkdir(parents=True, exist_ok=True)
            Path(task.txt_dir).mkdir(parents=True, exist_ok=True)

            file_stem = utils.clean_filename(meta.title)

            if failed_chapters:
                failed_path = Path(task.txt_dir) / f"{file_stem}_failed.txt"
                exporters.save_failed_report(meta, failed_chapters, failed_path)
                print(f"[*] 失败报告: {failed_path.resolve()}")

            epub_path = Path(task.epub_dir) / f"{file_stem}.epub"
            txt_path = Path(task.txt_dir) / f"{file_stem}.txt"

            exporters.build_epub(meta, chapters, epub_path, session)
            exporters.save_txt(meta, chapters, txt_path)

            print("[*] 下载完成!")
            print(f"[*] EPUB: {epub_path.resolve()}")
            print(f"[*] TXT : {txt_path.resolve()}")
            print(f"[*] 成功: {len(chapters)} 章")
            print(f"[*] 失败: {len(failed_chapters)} 章")
        finally:
            for k, v in _saved_dirs.items():
                setattr(config, k, v)

    def _download_finished(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self._stop_event.is_set():
            self._set_status("已停止")
        else:
            self._set_progress(1.0)
            self._set_status("队列完成")


def run_gui():
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = NovalPieApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
