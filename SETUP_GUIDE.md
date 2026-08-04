---
name: qq-bilibili-bot-setup
description: 从零搭建 QQ 群聊 B站视频下载机器人（NapCatQQ + Python + yt-dlp），包含完整踩坑记录
metadata:
  type: project
---

# QQ 群聊 B站视频下载机器人 — 完整搭建指南

## 架构总览

```
QQ群消息 → NapCatQQ (OneBot v11 WebSocket) → Python Bot
    │                                              │
    ├─ B站 App 分享到 QQ → JSON 卡片消息            │
    │  (B站链接藏在 qqdocurl 字段，斜杠被转义为 \/)   │
    │                                              │
    └─ Bot 流程:                                   │
       1. 正则提取 BV号（含 \/ → / 还原）            │
       2. B站公开 API 获取视频信息                   │
       3. yt-dlp 下载 worstvideo（纯视频 360p）       │
       4. CQ:video 码发回群内                       │
       5. 每天 15:00 清理 E:\BiliBot_TempVideos     │
```

## 环境要求

- Windows 10/11 x64
- Python 3.9+（推荐 3.14，已测试）
- QQ 桌面版 9.9.26+（E:\QQ.exe）
- 一个 QQ 机器人账号

## 第一步：安装 NapCatQQ

### 下载
从 https://github.com/NapNeko/NapCatQQ/releases/latest 下载 `NapCat.Shell.Windows.Node.zip`（约 110MB，内置 Node.js + NapCatQQ 完整环境）。

### 解压
解压到纯英文路径（无空格、无中文），例如：`C:\Users\00\qq-bili-bot\NapCatQQ_Node\`

### 配置 OneBot WebSocket
编辑 `NapCatQQ_Node\napcat\config\onebot11_<你的QQ号>.json`：

```json
{
  "enable": true,
  "network": {
    "httpServers": [],
    "httpSseServers": [],
    "httpClients": [],
    "websocketServers": [
      {
        "name": "bili-bot",
        "enable": true,
        "host": "0.0.0.0",
        "port": 3001,
        "heartInterval": 30000
      }
    ],
    "websocketClients": [],
    "plugins": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": false,
  "parseMultMsg": false,
  "imageDownloadProxy": "",
  "timeout": {
    "baseTimeout": 10000,
    "uploadSpeedKBps": 256,
    "downloadSpeedKBps": 256,
    "maxTimeout": 1800000
  }
}
```

关键点：`"enable": true` 和 `websocketServers` 都必须有。

### 修复启动脚本
编辑 `NapCatQQ_Node\napcat\launcher-win10.bat`，在 `@echo off` 后加一行 `cd /d "%~dp0"`，解决管理员运行时工作目录变成 `C:\Windows\system32` 的问题。

### 对齐 QQ 版本
编辑 `NapCatQQ_Node\config.json`，把 `baseVersion` 和 `curVersion` 改成你实际安装的 QQ 版本号（例如 `9.9.26-44498`）。版本不匹配会导致 QQ 闪退。

### 首次启动
右键 → 以管理员身份运行 `launcher-win10.bat`，扫码登录。

## 第二步：安装 Python 依赖

```bash
pip install websockets>=12.0 requests>=2.31.0 yt-dlp>=2024.0.0
```

## 第三步：部署 Bot 代码

### 文件结构

```
qq-bili-bot/
├── main.py            # 主入口：WebSocket 连接 + 消息路由
├── config.py          # 集中配置
├── link_parser.py     # 链接解析（长链 + 短链 + JSON卡片）
├── video_info.py      # B站 API 获取视频信息
├── downloader.py      # yt-dlp 下载封装
├── cleanup.py         # 临时文件清理
└── requirements.txt   # pip 依赖
```

### config.py 关键配置

```python
NAPCAT_WS_URL = "ws://localhost:3001"
TEMP_DIR = r"E:\BiliBot_TempVideos"    # E盘独立暂存目录
ALLOWED_GROUPS = [YOUR_GROUP_ID]            # 群白名单
MAX_FILE_SIZE = 100 * 1024 * 1024       # 100MB
RECONNECT_DELAY = 5                      # 断线重连间隔
```

### 启动 Bot

```bash
cd C:\Users\00\qq-bili-bot
python main.py
```

## 核心踩坑记录

### 坑 1：QQ 桌面版把 B站链接转成了 JSON 卡片

**现象**：B站 App 分享到 QQ 后，Bot 收到的 `raw_message` 是 `[CQ:json,data=...]` 格式，原始 URL 不直接可见。

**根因**：QQ 将 B站链接渲染为小程序卡片，URL 被埋在 JSON 深层字段 `meta.detail_1.qqdocurl` 中，且斜杠被转义为 `\/`。

**解决**：在 `link_parser.py` 的 `extract_bv_from_message()` 开头加：
```python
text = text.replace(r"\/", "/")  # 还原 JSON 中转义的斜杠
```
这样正则就能在 `https:\/\/b23.tv\/xxx` 中匹配到短链接。

### 坑 2：ffmpeg 未安装导致 DASH 流合并失败

**现象**：`ERROR: You have requested merging of multiple formats but ffmpeg is not installed`

**根因**：yt-dlp 默认格式 `worstvideo+worstaudio` 需要 ffmpeg 合并音视频。

**解决**：改用 `format: "worstvideo"`（纯视频流，360p，无需合并）。注意这样下载的视频没有音频，但文件体积最小，适合群文件发送。

### 坑 3：部分 B站视频只有 DASH 分离流

**现象**：`Requested format is not available`

**根因**：B站未登录状态下，多数视频只提供音视频分离的 DASH 流，没有合并流。`worst` 格式找不到匹配。

**解决**：用 `worstvideo` 而非 `worst`。用脚本列出可用格式确认：
```python
import yt_dlp
ydl = yt_dlp.YoutubeDL({'quiet': True, 'http_headers': {...}})
info = ydl.extract_info(url, download=False)
for f in info['formats']:
    print(f['format_id'], f['ext'], f.get('resolution'), f.get('vcodec'), f.get('acodec'))
```

### 坑 4：B站 HTTP 412 风控

**现象**：`HTTP Error 412: Precondition Failed`

**解决**：yt-dlp 需要正确的 HTTP 头：
```python
"http_headers": {
    "User-Agent": "Mozilla/5.0 ... Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
},
```

### 坑 5：NapCat 启动脚本管理员运行路径错误

**现象**：`'.\NapCatWinBootMain.exe' is not recognized`

**根因**：管理员运行时，CMD 工作目录变为 `C:\Windows\system32`，相对路径失效。

**解决**：在 `launcher-win10.bat` 的 `@echo off` 后紧接着加 `cd /d "%~dp0"`。

### 坑 6：QQ 版本与 NapCat 不匹配导致闪退

**现象**：QQ 启动后立即崩溃，日志中报 `implementation of IKernelSettingService is not valid`。

**根因**：NapCatQQ 的 `wrapper.node`（97MB 原生模块）是针对特定 QQ 版本编译的。`config.json` 中的 `baseVersion` 与安装的 QQ 版本不一致。

**解决**：修改 `NapCatQQ_Node\config.json` 中的 `baseVersion` 和 `curVersion` 为实际 QQ 版本号。通过 PowerShell 查看：`(Get-Item "E:\QQ.exe").VersionInfo.FileVersion`。

**版本矩阵参考**：
- NapCatQQ v4.18.5 → QQ 9.9.27-45627（推荐）
- QQ 9.9.26-44498 → 可用但不完全匹配，修改 config.json 后勉强能用
- QQ 9.9.7 → 太旧，不可用

### 坑 7：文件路径问题

**现象**：NapCat 报 `ENOENT: no such file or directory, open 'C:\Users\00\temp_videos\xxx.mp4'`

**根因**：Bot 工作目录是 `C:\Users\00` 而非脚本目录，`./temp_videos` 解析到了错误位置。

**解决**：`config.py` 中使用绝对路径：
```python
TEMP_DIR = r"E:\BiliBot_TempVideos"
```

### 坑 8：文件过早删除

**现象**：消息发出但 NapCat 读不到文件。

**根因**：`send_group_video()` 是 fire-and-forget，消息刚发出 `finally` 块就删了文件。

**解决**：改为每天下午 15:00 统一清理 `E:\BiliBot_TempVideos\`。删除 `finally` 中逐次清理的逻辑，添加 `daily_cleanup_scheduler()` 协程。

### 坑 9：Windows 控制台 GBK 编码

**现象**：`UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f9f9'`

**解决**：在 `main.py` 日志配置前加：
```python
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

### 坑 10：OneBot 配置位置

**现象**：改了 `napcat.json` 但 WebSocket 不生效。

**根因**：OneBot v11 的 WebSocket 配置在 `onebot11_<QQ号>.json` 中，不是在 `napcat.json` 中。

## 日常使用

### 启动顺序
1. 右键管理员运行 `NapCatQQ_Node\napcat\launcher-win10.bat` → 扫码登录
2. 终端执行 `python main.py`

### 触发方式
从 B站 App 分享视频到 QQ 群 → 自动下载 360p 纯视频 → 发回群内。

### 文件清理
每天下午 15:00 自动清空 `E:\BiliBot_TempVideos\`。

### 群白名单
仅响应 `config.py` 中 `ALLOWED_GROUPS` 列表内群号的消息。其他群静默忽略。

## 技术细节

### 下载格式选择
- `worstvideo`：最差画质纯视频流（360p AVC），无需 ffmpeg，文件约 10-50MB
- 不加 `+worstaudio`：因为需要 ffmpeg 合并
- 不要用 `worst`：B站未登录时通常没有合并流

### URL 提取兼容性
- 纯文本长链接：`bilibili.com/video/BVxxx`
- 纯文本短链接：`b23.tv/xxx`
- JSON 卡片：`meta.detail_1.qqdocurl` 中的转义 URL
- 所有 URL 的 `\/` 都被还原为 `/`

### 消息发送
- 使用 OneBot v11 CQ 码：`[CQ:video,file=file:///E:/BiliBot_TempVideos/BVxxx.mp4]`
- 视频前附带标题和 UP主信息
- 错误时群内发送友好提示，不崩溃
