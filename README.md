# QQ 群聊多功能机器人 (BiliBot)

基于 NapCatQQ (OneBot v11) + Python 的 QQ 群聊机器人，支持 **B站视频下载**、**JM 漫画下载**、**Pixiv 插画**、**多音色语音合成**、**AI 角色人设对话（含好感度系统）** 以及 **Web 管理面板**。

## 功能

- **B站视频下载** — 自动识别群内 B站链接（`bilibili.com/video/BVxxx`、`b23.tv` 短链），下载低画质视频发回群
- **JM 漫画下载** — `/jm <ID>` 下载漫画章节为 PDF，支持详情、封面、排行榜
- **Pixiv 插画** — `/pixiv search <关键词>` 搜索、`/pixiv rank` 排行榜、`/pixiv <ID>` 下载原图（经本地代理访问 Pixiv API）
- **语音合成** — `/say <文本>` 用多角色音色（爱莉希雅 / 洛琪希 / 神里绫华 / 流萤）发语音条，`/voice` 切换音色
- **AI 角色对话** — `/ai <文本>` 与角色人设聊天（DeepSeek 驱动），回复通过对应音色语音或文字发出
- **人设系统** — `/persona` 切换 AI 角色，支持"像真人一样"连续发多条消息
- **好感度系统** — 每个角色/群/用户独立好感度（0~100），内容越好越涨、越差越掉；0 分不回复
- **管理面板** — 二次元风格的 Web 界面（`admin/`），可视化配置白名单 / 音色 / AI / 好感度 / 功能开关 / 日志

## 架构

```
QQ 群消息 → NapCatQQ (OneBot v11) → WebSocket → Python Bot (main.py)
                                                        │
                              ┌─────────────┬──────────┼──────────┬──────────┐
                          B站视频      JM 漫画     Pixiv 插画    语音合成      AI 对话
                                                                   │            │
                                                      本地 GPT-SoVITS    DeepSeek API
                                                      (反向隧道 9881)    (人设卡+好感度)

Web 管理面板 (admin/admin_server.py, :8080) ⇄ admin_config.json ⇄ Bot 每 30s 热加载
```

- **语音**：GPT-SoVITS 跑在本地电脑（`voice/voice_daemon.py`），通过反向 SSH 隧道把服务器 `9881` 转发到本地 `9880`；bot 调用 `/tts` 合成
- **AI**：DeepSeek `deepseek-chat`，人设卡在 `ai_personas.py`，密钥在 `ai_secret.py`（不入库）
- **管理面板**：独立 FastAPI 进程，令牌鉴权；修改 `admin_config.json`，bot 每 30 秒热加载，白名单/音色/AI 参数改完即生效

## 安装

```bash
pip install -r requirements.txt
```

系统依赖：**ffmpeg**（B站视频合并时需要）。

## 配置

```bash
cp config.example.py config.py
cp ai_secret.example.py ai_secret.py
cp admin/admin_config.example.json admin/admin_config.json
# 编辑三个文件填入你的参数
```

| 配置项 | 说明 |
|--------|------|
| `NAPCAT_WS_URL` | NapCatQQ WebSocket 地址，默认 `ws://localhost:3001` |
| `ALLOWED_GROUPS` | 群白名单 |
| `COMIC_ALLOWED_USERS` | 私聊白名单 QQ 号 |
| `VOICE_CONTROL_USERS` | 管理员 QQ 号（切换音色/人设/设置好感度） |
| `PIXIV_REFRESH_TOKEN` | Pixiv OAuth Refresh Token |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（`ai_secret.py`） |
| `VOICES` | 音色表（权重路径 / 参考音频 / 提示文本 / 语速） |
| `admin/admin_config.json` | 运行时配置（白名单 / 音色参数 / AI 人设 / 好感度） |

## 运行

```bash
python main.py              # 主机器人
python admin/admin_server.py # 管理面板（或 systemctl start admin）
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
| `/jm rank [week]` | 排行榜 TOP10 |

### Pixiv

| 命令 | 说明 |
|------|------|
| `/pixiv rank [day\|week\|month]` | 排行榜（含缩略图） |
| `/pixiv search <关键词>` | 搜索插画（含缩略图） |
| `/pixiv <作品ID>` | 下载原图 |

### 语音

| 命令 | 说明 |
|------|------|
| `/say <文本>` | 当前音色语音条 |
| `/say <音色> <文本>` | 指定音色语音条 |
| `/voice` | 查看音色 |
| `/voice <音色>` | 切换音色（仅管理员） |
| `/sayto <QQ> <文本>` | 指定 QQ 发语音（仅管理员） |

### AI 对话

| 命令 | 说明 |
|------|------|
| `/ai <文本>` | 与当前人设 AI 对话（语音回复） |
| `/ai <人设> <文本>` | 指定人设对话 |
| `/persona` | 查看人设 |
| `/persona <人设>` | 切换人设（仅管理员） |
| `/openvoice` / `/offvoice` | AI 语音回复开关（仅管理员） |

### 好感度

| 命令 | 说明 |
|------|------|
| `/aff` | 查看当前人设下自己的好感度 |
| `/aff rank` | 群聊好感度排行 |
| `/aff set <QQ> <0-100>` | 设置好感度（仅管理员） |
| `/aff reset <QQ\|all>` | 重置好感度（仅管理员） |

好感度初始 50（0~100），每次对话按内容情绪自动增减（热情+3 / 友善+2 / 中性+1 / 冷淡-2 / 不耐烦-4 / 指责-6 / 恶意-10），0 分不回复。

### 通用

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |

## 项目结构

```
├── main.py               # 主入口 / WebSocket / 消息路由
├── config.example.py     # 配置模板
├── downloader.py         # B站视频下载
├── link_parser.py        # B站链接识别
├── video_info.py         # B站 API 信息查询
├── comic_downloader.py   # JM 漫画下载 + PDF 导出
├── comic_commands.py     # JM 命令（info / cover / rank）
├── pixiv_handler.py      # Pixiv API 封装
├── pixiv_auth.py         # Pixiv OAuth Token 获取工具
├── tunnel_daemon.py      # 隧道守护（可选）
├── cleaner.py / cleanup.py  # 定时清理
├── voice_handler.py      # 多音色语音合成（GPT-SoVITS）
├── ai_handler.py         # AI 对话 / 人设 / 好感度 / 队列
├── ai_personas.py        # AI 人设卡（角色设定）
├── ai_secret.example.py  # DeepSeek 密钥模板
├── help_text.py          # /help 命令文本
├── requirements.txt      # pip 依赖
├── admin/                # 管理面板
│   ├── admin_server.py       # FastAPI 后端（:8080）
│   ├── admin_config.example.json  # 运行时配置模板
│   └── static/               # 二次元风格前端（樱花主题）
└── SETUP_GUIDE.md        # 部署指南
```

## 技术栈

- [NapCatQQ](https://github.com/NapNeko/NapCatQQ) — QQ 协议端
- [OneBot v11](https://onebot.dev/) — 消息协议
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — 语音合成
- [DeepSeek](https://platform.deepseek.com/) — AI 对话
- [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) — 漫画下载
- [FastAPI](https://fastapi.tiangolo.com/) — 管理面板后端

## 隐私说明

- 密钥（DeepSeek / Pixiv / 管理令牌）与运行时数据（`admin_config.json`、`ai_affection.json`）均在 `.gitignore` 中，不入库
- 部署到自己的服务器时，请修改默认的管理令牌

## License

MIT