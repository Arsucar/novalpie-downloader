# novalpie 小说导出工具（EPUB/TXT）

基于 `Python + Playwright` 的 `novalpie.cc` 小说抓取脚本，主程序位于：

- `novalpie.py`

脚本会自动抓取章节内容并导出：

- `EPUB`（支持插图嵌入）
- `TXT`（正文 + 图片链接）

## 功能特性

- 支持从任意章节 URL 开始抓取
- 优先通过章节列表接口获取完整目录，失败时自动回退 HTML 解析
- 自动处理“章节正文混入前后章节内容”问题：
  - 先定位当前章节标题
  - 读取到下一章节标题即截断
- 自动去除评论区污染文本（如“章节讨论 / 展开评论 / 暂无评论”等）
- 自动提取章节内图片并嵌入 EPUB
- 支持失败重试、抓取间隔、首章额外等待等稳定性配置

## 环境要求

- Python 3.10+
- Windows / Linux / macOS

Python 依赖：

- `requests`
- `beautifulsoup4`
- `lxml`
- `ebooklib`
- `playwright`

## 安装

在仓库根目录执行：

```bash
pip install requests beautifulsoup4 lxml ebooklib playwright
playwright install chromium
```

## 快速开始

1. 编辑配置文件：`novalpie.py`
2. （可选）在目录创建 `novalpie.txt`，第一行写入 Cookie
3. 运行脚本

```bash
python novalpie.py
```

## 关键配置项

以下配置都在 `esj/novalpie.py` 顶部：

- `bookURL`：起始章节链接（必改）
- `base_url`：站点根地址，需与 `bookURL` 同域名
- `cookieFilePath`：Cookie 文件路径（默认 `./novalpie.txt`）
- `headless`：是否无头运行浏览器（`True/False`）
- `chapterDelayMinSec` / `chapterDelayMaxSec`：章节访问间隔（秒）
- `firstChapterExtraWaitSec`：首章额外等待时间（秒）
- `chapterReadyTimeoutSec`：单章正文等待超时（秒）
- `pageGotoTimeoutMs`：页面加载超时（毫秒）
- `retryPerChapter`：单章失败重试次数
- `maxChapters`：最多抓取章节数，`0` 表示不限制
- `startFromCurrentChapter`：
  - `True` 从 `bookURL` 指向章节开始抓
  - `False` 从第 1 章开始抓
- `keepFailedChapterPlaceholder`：是否保留抓取失败章节占位文本
- `epubOutputDir` / `txtOutputDir`：输出目录

## Cookie 格式

`novalpie.txt` 第一行示例：

```txt
key1=value1; key2=value2; key3=value3;
```

如果不提供 Cookie，脚本会尝试无登录抓取。

## 输出说明

默认输出目录：

- `./epubBooks_novalpie`
- `./txtBooks_novalpie`

文件名默认使用书名自动清洗非法字符。

## 插图行为说明

- 脚本会在“当前章标题 -> 下一章标题”正文窗口内提取图片 URL
- 下载图片后嵌入 EPUB 章节内容
- TXT 末尾会追加 `[Images]` 区块，保存该章图片链接
- 部分防盗链图片若下载失败会自动跳过，不影响整章导出

## 常见问题

### 1) 为什么要用浏览器（Playwright）？

`novalpie` 的章节内容由前端动态渲染，纯 `requests` 通常拿不到最终正文，或会混入非目标内容。浏览器上下文提取更稳定。

### 2) 抓不到章节列表怎么办？

脚本会先尝试接口，再自动回退页面解析。若仍失败，通常是 Cookie 失效或访问受限，建议更新 Cookie 后重试。

### 3) 运行很慢？

可适当降低：

- `firstChapterExtraWaitSec`
- `chapterDelayMinSec/chapterDelayMaxSec`

但间隔过低可能导致渲染不完整或触发风控。

## 合规与声明

本项目仅用于个人学习与备份。请遵守目标网站的服务条款、版权要求及当地法律法规。请勿用于任何商业化或侵权用途。
