# QQ 群聊多功能机器人 (BiliBot)

基于 NapCatQQ (OneBot v11) + Python 的 QQ 群聊机器人，支持 **B站视频下载**、**JM漫画下载**、**Pixiv 插画搜索/排行/下载**。

## 功能

- **B站视频下载** — 自动识别群内 B站链接 (bilibili.com / b23.tv)，下载低画质视频发回群
- **JM漫画下载** — `/jm <ID>` 下载漫画章节为 PDF，支持 `/jm info` 查看详情、`/jm rank` 排行榜
- **Pixiv 插画** — `/pixiv search <关键词>` 搜索、`/pixiv rank` 排行榜、`/pixiv <ID>` 下载原图
- **帮助** — `/help` 查看所有命令

## 架构

```
QQ 群消息 → NapCatQQ (Docker/Win) → WebSocket (ws://) → Python Bot (本服务)
                                                              │
                                                    ┌─────────┼─────────┐
                                                 B站视频   JM漫画   Pixiv插画
```

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
| `ALLOWED_GROUPS` | 群白名单，这些群内可用 B站/JM 功能 |
| `COMIC_ALLOWED_USERS` | 私聊 JM/Pixiv 功能白名单 QQ 号 |
| `PIXIV_REFRESH_TOKEN` | Pixiv OAuth Refresh Token（获取方法见 SETUP_GUIDE） |

## 运行

```bash
python main.py
```

Pixiv 功能需要代理隧道（日本 IP），在能翻墙的电脑上：

```bash
python tunnel_daemon.py
```

## 命令

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
| `/pixiv rank [day|week|month]` | 排行榜（含缩略图） |
| `/pixiv search <关键词>` | 搜索插画（含缩略图） |
| `/pixiv <作品ID>` | 下载原图 |

### 通用

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |

## 技术栈

- [NapCatQQ](https://github.com/NapNeko/NapCatQQ) — QQ 协议端
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — B站视频下载
- [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) — 漫画下载
- [pixivpy3](https://github.com/upbit/pixivpy) — Pixiv API
- [Mihomo](https://github.com/MetaCubeX/mihomo) — 代理

## License

MIT
