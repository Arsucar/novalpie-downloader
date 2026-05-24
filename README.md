# novalpie 小说导出工具（EPUB/TXT）

基于 `Python + Playwright` 的 `novalpie.cc` 小说抓取工具，支持命令行和 GUI 两种使用方式。

## 功能特性

- **GUI 图形界面**：基于 customtkinter 的现代化界面，支持实时进度、速率统计、日志查看
- **浏览器登录获取 Cookie**：内置登录脚本，解决浏览器扩展无法导出 Cookie 的问题
- **JWT Token 认证**：支持 localStorage 中存储的 JWT token 自动提取
- **智能章节抓取**：
  - 优先通过章节列表接口获取完整目录，失败时自动回退 HTML 解析
  - 自动处理"章节正文混入前后章节内容"问题
  - 自动去除评论区污染文本
- **多格式导出**：EPUB（支持插图嵌入）/ TXT（正文 + 图片链接）
- **性能统计**：实时显示下载速率（章/秒）、预计剩余时间、每章用时
- **预设提速方案**：一键切换保守/均衡/激进三种下载参数配置
- **缓存机制**：已下载章节自动缓存，断点续传无需重复抓取

## 环境要求

- Python 3.10+
- Windows / Linux / macOS

## 安装

在仓库根目录执行：

```bash
pip install -e .
playwright install chromium
```

或手动安装依赖：

```bash
pip install requests beautifulsoup4 lxml ebooklib playwright customtkinter
playwright install chromium
```

## 快速开始

### GUI 模式（推荐）

```bash
python -m novalpie.gui
```

或在安装后直接运行：

```bash
novalpie-gui
```

### 命令行模式

```bash
python run.py
```

或：

```bash
novalpie
```

## 首次使用：获取 Cookie

由于站点使用 localStorage 存储 JWT token 进行认证，常规浏览器扩展无法导出。请使用内置登录脚本：

或直接F12打开浏览器控制台，执行以下代码：
`localStorage.auth_token` 复制其输出内容保存到 `novalpie.token` 文件中

```bash
python -m novalpie.login_cookie
```

脚本会打开浏览器，手动登录后自动提取 token 并保存到 `novalpie.token` 和 `novalpie.txt`。

## GUI 使用说明

### 基本设置

- **书籍章节链接**：粘贴起始章节的 URL
- **站点根地址**：通常为 `https://novalpie.cc/`
- **Cookie 文件路径**：登录脚本自动生成的文件路径

### 下载设置

- **预设方案**：一键切换下载参数
  - **保守**：间隔 1.0~1.5s，超时 20s，重试 2 次（推荐）
  - **均衡**：间隔 0.8~1.2s，超时 15s，重试 2 次
  - **激进**：间隔 0.5~1.0s，超时 15s，重试 1 次（有封号风险）
- **章节间隔**：两次请求之间的随机延迟（秒）
- **章节超时**：单章内容加载的最大等待时间
- **重试次数**：单章失败后的重试次数
- **最大章节数**：0 表示不限制

### 选项

- **无头模式**：是否在后台运行浏览器（不显示窗口）
- **从当前章节开始**：从 URL 指向的章节开始，或从第 1 章开始
- **保留失败章节占位**：失败章节是否保留占位文本

### 字体大小

界面右下角提供字体大小滑块，可动态调整全局字体大小。

## 关键配置项

命令行模式下，编辑 `src/novalpie/config.py`：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `bookURL` | 起始章节链接 | 需修改 |
| `base_url` | 站点根地址 | `https://novalpie.cc/` |
| `cookieFilePath` | Cookie 文件路径 | `./novalpie.txt` |
| `headless` | 无头运行浏览器 | `True` |
| `chapterDelayMinSec/MaxSec` | 章节访问间隔（秒） | `1.0 / 1.5` |
| `firstChapterExtraWaitSec` | 首章额外等待（秒） | `3` |
| `chapterReadyTimeoutSec` | 单章等待超时（秒） | `20` |
| `pageGotoTimeoutMs` | 页面加载超时（毫秒） | `130000` |
| `retryPerChapter` | 单章失败重试次数 | `2` |
| `maxChapters` | 最多抓取章节数（0=不限） | `0` |
| `startFromCurrentChapter` | 从当前章节开始 | `True` |
| `keepFailedChapterPlaceholder` | 保留失败章节占位 | `True` |
| `epubOutputDir` | EPUB 输出目录 | `./epubBooks_novalpie` |
| `txtOutputDir` | TXT 输出目录 | `./txtBooks_novalpie` |
| `cacheOutputDir` | 缓存目录 | `./cache_novalpie` |

## Cookie 格式

`novalpie.txt` 第一行示例：

```txt
key1=value1; key2=value2; key3=value3;
```

JWT token 单独保存在 `novalpie.token` 文件中，程序会自动读取并通过 `Authorization: Bearer` 请求头发送。

## 输出说明

默认输出目录：

- `./epubBooks_novalpie`
- `./txtBooks_novalpie`

文件名默认使用书名自动清洗非法字符。

## 插图行为说明

- 脚本会在"当前章标题 -> 下一章标题"正文窗口内提取图片 URL
- 下载图片后嵌入 EPUB 章节内容
- TXT 末尾会追加 `[Images]` 区块，保存该章图片链接
- 部分防盗链图片若下载失败会自动跳过，不影响整章导出

## 项目结构

```
├── src/novalpie/
│   ├── __init__.py
│   ├── browser.py      # 章节下载核心逻辑
│   ├── cache.py        # 章节缓存管理
│   ├── config.py       # 配置文件
│   ├── exporters.py    # EPUB/TXT 导出
│   ├── gui.py          # GUI 界面
│   ├── login_cookie.py # 登录获取 Cookie 脚本
│   ├── network.py      # 网络请求封装
│   └── utils.py        # 工具函数
├── run.py              # 命令行入口
├── pyproject.toml      # 项目配置
└── README.md
```

## 常见问题

### 1) 为什么要用浏览器（Playwright）？

`novalpie` 的章节内容由前端动态渲染，纯 `requests` 通常拿不到最终正文，或会混入非目标内容。浏览器上下文提取更稳定。

### 2) 抓不到章节列表怎么办？

脚本会先尝试接口，再自动回退页面解析。若仍失败，通常是 Cookie 失效或访问受限，建议运行 `python -m novalpie.login_cookie` 重新登录后重试。

### 3) 运行很慢？

GUI 中可切换"均衡"或"激进"预设方案提速。命令行模式下可调整 `config.py` 中的间隔参数，但间隔过低可能导致渲染不完整或触发风控。

### 4) 日志中显示认证失败？

站点使用 JWT token 认证而非传统 Cookie。请确保 `novalpie.token` 文件存在且 token 有效。运行登录脚本可自动更新 token。

## 合规与声明

本项目仅用于个人学习与备份。请遵守目标网站的服务条款、版权要求及当地法律法规。请勿用于任何商业化或侵权用途。
