# QQ 群聊多功能机器人 (BiliBot)

基于 NapCatQQ (OneBot v11) + Python 的 QQ 群聊机器人，支持 **B站视频下载**、**JM 漫画下载**、**Pixiv 插画搜索/排行/下载**、**AI 语音对话**（DeepSeek + GPT-SoVITS）、**好感度**、**定时语音宽慰**与**音色自动轮换**，并带一个二次元风格的管理面板。

## 功能

- **B站视频下载** — 自动识别群内 B站链接（`bilibili.com/video/BVxxx`、`b23.tv`），下载低画质视频发回群
- **JM 漫画下载** — `/jm <ID>` 下载漫画章节为 PDF，支持详情、封面、排行榜
- **Pixiv 插画** — `/pixiv search <关键词>` 搜索、`/pixiv rank` 排行榜、`/pixiv <ID>` 下载原图
- **AI 语音对话** — 12 个二次元人设（爱莉希雅/希儿/花火/胡桃等），AI 回复可用 GPT-SoVITS 合成对应角色语音
- **好感度** — 每个人设/会话独立好感度，影响 AI 回复态度
- **定时宽慰** — 每天 9:00 / 18:30 / 23:30 三段长文语音（音色轮播）
- **音色轮换** — 定时宽慰按音色顺序轮播；日常默认音色每天自动换一个
- **管理面板** — Web 前端（端口 8080）配置白名单 / 音色 / 人设 / 好感度
- **帮助** — `/help` 查看所有命令

## 架构

```
QQ 群消息 → NapCatQQ (Docker / Windows) → WebSocket → Python Bot
                                                          │
                                            ┌─────────────┼─────────────┐
                                         B站视频      JM 漫画      Pixiv 插画
```

- **B站视频**：B站 API 直连下载，无需登录
- **JM 漫画**：基于 jmcomic 库下载图片并合并为 PDF
- **Pixiv 插画**：通过本地代理访问 Pixiv API（代理地址在 `config.py` 中配置）
- **AI 语音**：DeepSeek 生成回复 → 本地 GPT-SoVITS 合成角色语音（服务器经反向 SSH 隧道调用本地 API）

## 安装

```bash
pip install -r requirements.txt
```

系统依赖：**ffmpeg**（B站视频合并时需要）

## 配置

```bash
cp config.example.py config.py
# 编辑 config.py 填入你的配置
```

| 配置项 | 说明 |
|--------|------|
| `NAPCAT_WS_URL` | NapCatQQ WebSocket 地址，默认 `ws://localhost:3001` |
| `ALLOWED_GROUPS` | 群白名单，这些群内可用 B站 / JM 功能 |
| `COMIC_ALLOWED_USERS` | 私聊 JM / Pixiv 功能白名单 QQ 号 |
| `PIXIV_REFRESH_TOKEN` | Pixiv OAuth Refresh Token |

## 运行

```bash
python main.py
```

## 命令

### B站视频

直接在群里发送 B站链接即可，无需命令。

### JM 漫画

| 命令 | 说明 |
|------|------|
| `/jm <ID>` | 下载漫画 PDF |
| `/jm info <ID>` | 查看详情（作者、标签、章节） |
| `/jm cover <ID>` | 发送封面图 |
| `/jm rank` | 周排行榜 TOP10 |

### Pixiv

| 命令 | 说明 |
|------|------|
| `/pixiv rank [day\|week\|month]` | 排行榜（含缩略图） |
| `/pixiv search <关键词>` | 搜索插画（含缩略图） |
| `/pixiv <作品ID>` | 下载原图 |

### AI 语音对话

| 命令 | 说明 |
|------|------|
| `/ai <文本>` | 与当前人设 AI 语音对话 |
| `/ai <人设> <文本>` | 指定人设对话 |
| `/persona` | 查看人设；`/persona <人设>` 切换（管理员） |
| `/openvoice` / `/offvoice` | 语音回复开关（管理员） |

### 语音与音色

| 命令 | 说明 |
|------|------|
| `/voice` | 查看可用音色 |
| `/voice <音色>` | 切换默认音色（管理员，不改变自动轮换顺序） |
| `/say <文本>` | 用默认音色发语音条 |
| `/say <音色> <文本>` | 指定音色发语音条 |
| `/sayto <QQ> <文本>` | 给指定 QQ 发语音（管理员） |

### 好感度

| 命令 | 说明 |
|------|------|
| `/aff` | 查看当前人设下自己的好感度 |
| `/aff rank` | 群聊好感度排行 |
| `/aff set <QQ> <0-100>` | 设置好感度（管理员） |
| `/aff reset <QQ\|all>` | 重置好感度（管理员） |

### 定时宽慰

| 命令 | 说明 |
|------|------|
| `/daily on` / `off` | 开启/关闭定时宽慰（管理员） |
| `/daily add <QQ或g群号>` | 添加目标 |
| `/daily test <morning\|evening\|night>` | 测试发送 |

### 通用

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |

## 项目结构

```
├── main.py              # 主入口 / WebSocket 连接 / 消息路由
├── config.example.py    # 配置模板
├── voice_handler.py     # 音色管理与 TTS 调用（GPT-SoVITS）
├── voice_rotation.py    # 音色自动轮换（宽慰轮播 + 每日轮换）
├── ai_handler.py        # DeepSeek 对话 / 上下文 / 好感度
├── ai_personas.py       # 12 个 AI 人设卡
├── daily_greeting.py    # 定时宽慰文案与目标管理
├── downloader.py        # B站视频下载
├── link_parser.py       # B站链接识别
├── video_info.py        # B站 API 信息查询
├── comic_downloader.py  # JM 漫画下载 + PDF 导出
├── comic_commands.py    # JM 命令（info / cover / rank）
├── pixiv_handler.py     # Pixiv API 封装
├── pixiv_auth.py        # Pixiv OAuth Token 获取工具
├── tunnel_daemon.py     # 隧道守护（可选）
├── admin/               # Web 管理面板（admin_server.py + static/）
├── cleaner.py           # 定时清理进程
├── help_text.py         # /help 命令文本
├── requirements.txt     # pip 依赖
└── SETUP_GUIDE.md       # 部署指南
```

## 技术栈

- [NapCatQQ](https://github.com/NapNeko/NapCatQQ) — QQ 协议端
- [OneBot v11](https://onebot.dev/) — 消息协议
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — B站视频下载
- [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) — 漫画下载
- [pixivpy3](https://github.com/upbit/pixivpy) — Pixiv API

## License

MIT
