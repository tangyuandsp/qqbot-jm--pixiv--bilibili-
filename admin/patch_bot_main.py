# -*- coding: utf-8 -*-
"""给 main.py 接入运行时配置：模块属性访问 + 功能开关 + 30秒热加载"""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/opt/bilibot/main.py"

with io.open(PATH, "r", encoding="utf-8") as f:
    c = f.read()


def rep(old, new, label, count=1):
    global c
    if old not in c:
        raise SystemExit(f"[{label}] marker not found")
    c = c.replace(old, new, count)


# 1. 导入 config 模块，去掉热加载项的 from-import
rep(
    """from config import (
    ALLOWED_GROUPS,
    COMIC_ALLOWED_USERS,
    COMIC_MAX_PDF_SIZE,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    NAPCAT_WS_URL,
    RECONNECT_DELAY,
    VOICES,
    VOICE_NAMES,
    VOICE_MAX_CHARS,
    VOICE_CONTROL_USERS,
)""",
    """import config
from config import (
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    NAPCAT_WS_URL,
    RECONNECT_DELAY,
)""",
    "import block",
)

# 2. 功能开关辅助函数
rep(
    'logger = logging.getLogger("BiliBot")',
    """logger = logging.getLogger("BiliBot")


def feature_enabled(name: str) -> bool:
    \"\"\"功能开关（从 admin_config.json 热加载，默认全开）\"\"\"
    return config.FEATURES.get(name, True)""",
    "feature_enabled",
)

# 3. 音色列表使用模块属性
rep(
    "        for n in VOICE_NAMES",
    "        for n in config.VOICE_NAMES",
    "voice_list_text",
)

# 4. 群白名单
rep(
    "    if group_id not in ALLOWED_GROUPS:",
    "    if group_id not in config.ALLOWED_GROUPS:",
    "group whitelist",
)

# 5. 群聊功能开关（插在 /help 之后）
rep(
    """    # ── /help ──
    if raw_message.strip() == "/help":
        await send_group_message(ws, group_id, HELP)
        return
""",
    """    # ── /help ──
    if raw_message.strip() == "/help":
        await send_group_message(ws, group_id, HELP)
        return

    # ── 功能开关（管理面板可停用） ──
    if raw_message.strip().startswith(("/voice", "/say", "/sayto")) and not feature_enabled("voice"):
        await send_group_message(ws, group_id, "⛔ 语音功能已由管理员停用~")
        return
    if raw_message.strip().startswith("/pixiv ") and not feature_enabled("pixiv"):
        await send_group_message(ws, group_id, "⛔ Pixiv 功能已由管理员停用~")
        return
    if raw_message.strip().startswith("/jm ") and not feature_enabled("jm"):
        await send_group_message(ws, group_id, "⛔ 漫画功能已由管理员停用~")
        return
""",
    "group feature gates",
)

# 6. B站功能开关（视频链接识别前）
rep(
    "    bv_id = extract_bv_from_message(raw_message)",
    """    if not feature_enabled("bili"):
        return

    bv_id = extract_bv_from_message(raw_message)""",
    "bili gate",
)

# 7. 群聊未知音色列表
rep(
    '                ws, group_id, f"❓ 未知音色，可用: {\' / \'.join(VOICE_NAMES)}"',
    '                ws, group_id, f"❓ 未知音色，可用: {\' / \'.join(config.VOICE_NAMES)}"',
    "group unknown voice",
)

# 8. 群聊语音管理员
rep(
    '        if event.get("user_id") not in VOICE_CONTROL_USERS:',
    '        if event.get("user_id") not in config.VOICE_CONTROL_USERS:',
    "group voice admin",
)

# 9. 私聊白名单
rep(
    "    if user_id not in COMIC_ALLOWED_USERS:",
    "    if user_id not in config.COMIC_ALLOWED_USERS:",
    "private whitelist",
)

# 10. 私聊功能开关（插在 /help 之后）
rep(
    """    if msg == "/help":
        await send_private_message(ws, user_id, HELP)
        return
""",
    """    if msg == "/help":
        await send_private_message(ws, user_id, HELP)
        return

    # ── 功能开关（管理面板可停用） ──
    if msg.startswith(("/voice", "/say", "/sayto")) and not feature_enabled("voice"):
        await send_private_message(ws, user_id, "⛔ 语音功能已由管理员停用~")
        return
    if msg.startswith("/pixiv ") and not feature_enabled("pixiv"):
        await send_private_message(ws, user_id, "⛔ Pixiv 功能已由管理员停用~")
        return
    if msg.startswith("/jm ") and not feature_enabled("jm"):
        await send_private_message(ws, user_id, "⛔ 漫画功能已由管理员停用~")
        return
""",
    "private feature gates",
)

# 11. 私聊未知音色列表
rep(
    '                ws, user_id, f"❓ 未知音色，可用: {\' / \'.join(VOICE_NAMES)}"',
    '                ws, user_id, f"❓ 未知音色，可用: {\' / \'.join(config.VOICE_NAMES)}"',
    "private unknown voice",
)

# 12. 私聊语音管理员
rep(
    "        elif user_id not in VOICE_CONTROL_USERS:",
    "        elif user_id not in config.VOICE_CONTROL_USERS:",
    "private voice admin",
)

# 13. /sayto 语音管理员
rep(
    "    if sender_id not in VOICE_CONTROL_USERS:",
    "    if sender_id not in config.VOICE_CONTROL_USERS:",
    "sayto admin",
)

# 14. 漫画 PDF 大小限制（全部）
rep(
    "        if pdf_size_mb > COMIC_MAX_PDF_SIZE:",
    "        if pdf_size_mb > config.COMIC_MAX_PDF_SIZE:",
    "comic size",
    count=0,
)

# 15. 语音最大字数（全部）
rep(
    "VOICE_MAX_CHARS",
    "config.VOICE_MAX_CHARS",
    "voice max chars",
    count=0,
)

# 16. 热加载任务定义
rep(
    "async def daily_cleanup():",
    """async def config_watch():
    \"\"\"每 30 秒热加载管理面板修改的配置（白名单/限制/音色参数/功能开关）\"\"\"
    while True:
        try:
            config.reload_runtime()
        except Exception as exc:
            logger.error(f"⚙️ 配置热加载失败: {exc}")
        await asyncio.sleep(30)


async def daily_cleanup():""",
    "config_watch def",
)

# 17. listen() 里启动热加载任务
rep(
    """    cleanup_temp_dir()
    logger.info("🧹 已清理遗留临时文件")
    asyncio.create_task(daily_cleanup())""",
    """    cleanup_temp_dir()
    logger.info("🧹 已清理遗留临时文件")
    asyncio.create_task(daily_cleanup())
    asyncio.create_task(config_watch())""",
    "config_watch start",
)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(c)
print("main.py patched OK")