# ============================================================
# QQ 群聊 B站视频下载机器人 �?配置文件（服务器版）
# ============================================================

# ── 正向 WebSocket：连接本�?NapCatQQ Docker 容器 ──
NAPCAT_WS_URL = "ws://localhost:3001"

# 视频临时下载目录
TEMP_DIR = "/opt/bilibot/temp_videos"

# 最大文件大小限制（100MB�?MAX_FILE_SIZE = 100 * 1024 * 1024

# 群白名单：只处理这些群的 B站链�?ALLOWED_GROUPS = [YOUR_GROUP_ID, YOUR_GROUP_ID_2]  # 汪汪队登duan�?+ 第二�?
# ── Pixiv 功能 ──
# Pixiv refresh_token（从浏览�?Cookie �?OAuth 获取�?# 获取方式: https://github.com/upbit/pixivpy/issues/158
PIXIV_REFRESH_TOKEN = "���_Pixiv_Refresh_Token_���_SETUP_GUIDE.md"
# QQ 号白名单：只有这�?QQ 号的 /jm 命令才会生效
COMIC_ALLOWED_USERS = [YOUR_QQ_ID, YOUR_BOT_QQ_ID]  # 你的大号 + 机器人号

# 漫画下载临时目录（服务器上）
COMIC_TEMP_DIR = "/opt/bilibot/temp_videos/comic"

# 漫画 PDF 最大文件大小（80MB，QQ 群文件上限约 100MB�?COMIC_MAX_PDF_SIZE = 80 * 1024 * 1024

# B�?API 请求�?BILIBILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 重连间隔（秒�?RECONNECT_DELAY = 5

# 日志
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
