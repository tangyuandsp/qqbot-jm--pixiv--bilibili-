#!/usr/bin/env python3
# ============================================================
# QQ 群聊 B站视频下载机器人 — 主入口（服务器版 / 正向 WebSocket）
# ============================================================
# Bot 连接本地 NapCatQQ Docker 容器的 WebSocket 服务端
# ============================================================

import asyncio
import datetime
import json
import logging
import os
import random
import re
import sys

import websockets

from cleanup import cleanup_temp_dir
from comic_downloader import download_comic
from comic_commands import download_cover, get_album_info, get_ranking
from pixiv_handler import (
    download_illust_img,
    ranking_illust,
    ranking_illust_with_thumbs,
    search_illust,
    search_illust_with_thumbs,
)
from help_text import HELP
import config
from config import (
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    NAPCAT_WS_URL,
    RECONNECT_DELAY,
)
from voice_handler import generate_voice, resolve_voice, switch_voice
import ai_handler
from downloader import download_video
from link_parser import extract_bv_from_message
from video_info import get_video_info

# ----------------------------------------------------------
# 日志
# ----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    stream=sys.stdout,
)
logger = logging.getLogger("BiliBot")


def feature_enabled(name: str) -> bool:
    """功能开关（从 admin_config.json 热加载，默认全开）"""
    return config.FEATURES.get(name, True)


# ----------------------------------------------------------
# OneBot v11 API
# ----------------------------------------------------------

async def send_group_message(ws, group_id: int, message: str) -> None:
    await ws.send(json.dumps({
        "action": "send_group_msg",
        "params": {"group_id": group_id, "message": message},
    }))


async def send_group_video(ws, group_id: int, filepath: str, caption: str = "") -> None:
    abs_path = os.path.abspath(filepath)
    cq_video = f"[CQ:video,file=file://{abs_path}]"
    message = f"{caption}\n{cq_video}" if caption else cq_video
    await send_group_message(ws, group_id, message)


async def send_group_file(ws, group_id: int, filepath: str) -> None:
    """向群发送文件（PDF等）"""
    abs_path = os.path.abspath(filepath).replace("\\", "/")
    await ws.send(json.dumps({
        "action": "upload_group_file",
        "params": {
            "group_id": group_id,
            "file": f"file:///{abs_path}",
            "name": os.path.basename(filepath),
        },
    }))


async def send_group_voice(ws, group_id: int, filepath: str) -> None:
    """向群发送语音条（NapCat 会把本地 wav 转成 QQ 语音）"""
    abs_path = os.path.abspath(filepath).replace("\\", "/")
    await send_group_message(ws, group_id, f"[CQ:record,file=file://{abs_path}]")


async def send_private_voice(ws, user_id: int, filepath: str) -> None:
    """向私聊发送语音条"""
    abs_path = os.path.abspath(filepath).replace("\\", "/")
    await send_private_message(ws, user_id, f"[CQ:record,file=file://{abs_path}]")


async def handle_comic_command(ws, group_id: int, user_id: int, comic_id: str):
    """处理 /jm 漫画下载命令 — 私聊/群聊分别发回 PDF"""
    logger.info(f"📚 漫画请求: group={group_id}, user={user_id}, id={comic_id}")
    try:
        await send_group_message(ws, group_id, f"📚 正在下载漫画 {comic_id}，请稍候...")

        pdf_path = await download_comic(comic_id)

        pdf_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if pdf_size_mb > COMIC_MAX_PDF_SIZE:
            await send_group_message(ws, group_id, f"😣 漫画 PDF 过大（{pdf_size_mb:.1f}MB），无法发送~")
            return

        logger.info(f"📚 漫画 PDF: {pdf_path} ({pdf_size_mb:.1f} MB)")

        abs_path = os.path.abspath(pdf_path).replace("\\", "/")
        filename = os.path.basename(pdf_path).replace('.pdf.pdf', '.pdf')
        await ws.send(json.dumps({
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": [
                    {"type": "text", "data": {"text": f"📚 {filename}"}},
                    {"type": "file", "data": {"file": f"file://{abs_path}", "name": filename}},
                ],
            },
        }))
        logger.info(f"📤 漫画 {comic_id} 发送成功")

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"❌ 漫画 {comic_id} 失败: {error_msg}")
        await send_group_message(ws, group_id, f"😣 漫画下载失败：{error_msg[:100]}")


# ----------------------------------------------------------
# 核心业务
# ----------------------------------------------------------

def voice_list_text() -> str:
    """音色列表提示文本"""
    from voice_handler import get_current_voice
    current = get_current_voice()
    lines = ["🎙️ 可用音色（4 种）:"]
    lines += [
        f"  {n}" + ("  ← 当前" if n == current else "")
        for n in config.VOICE_NAMES
    ]
    lines.append("切换: /voice <音色> （仅管理员）")
    lines.append("指定音色: /say <音色> <文本>")
    return "\n".join(lines)


async def do_switch_voice(ws, target_id: int, name: str, reply_fn):
    """管理员切换默认音色"""
    try:
        await reply_fn(f"🎙️ 正在切换音色 → {name} ...")
        await switch_voice(name)
        await reply_fn(f"✅ 已切换到「{name}」，/say 将使用该音色")
    except Exception as exc:
        logger.error(f"🎙️ 切换音色失败: {exc}")
        await reply_fn("🎙️ 切换失败：本地语音服务不可用，请稍后再试~")


def ai_persona_text() -> str:
    """人设列表提示文本"""
    current = ai_handler.get_current_persona()
    lines = ["🤖 可用人设："]
    lines += [
        f"  {n}" + ("  ← 当前" if n == current else "")
        for n in ai_handler.list_personas()
    ]
    if not current:
        lines.append("  （未设置，/ai 需带人设名或先 /persona 选择）")
    lines.append("切换: /persona <人设>（仅管理员）| /persona off 关闭")
    lines.append("对话: /ai <文本>  或  /ai <人设> <文本>")
    return "\n".join(lines)


async def do_switch_persona(ws, target_id: int, arg: str, reply_fn):
    """管理员切换/关闭当前人设"""
    if arg == "off":
        ai_handler.set_current_persona(None)
        await reply_fn("🤖 已关闭 AI 人设，/ai 需显式指定人设")
        return
    if arg in ai_handler.list_personas():
        ai_handler.set_current_persona(arg)
        await reply_fn(f"🤖 已切换到「{arg}」，用 /ai 文本 就能和我对话啦~")
    else:
        await reply_fn(f"❓ 未知人设，可用: {' / '.join(ai_handler.list_personas())}")


async def handle_ai_group(ws, group_id: int, text: str, persona_override: str = None, user_id: int = 0):
    """群聊 AI 语音回复（可能连续发多条，模拟真人节奏）"""
    persona_id = persona_override or ai_handler.get_current_persona()
    if not persona_id:
        await send_group_message(ws, group_id, ai_persona_text())
        return
    if ai_handler.get_affection(persona_id, "g%d" % group_id, user_id) <= 0:
        return  # 好感度为 0：不回复说话人
    try:
        loop = asyncio.get_running_loop()
        parts = await loop.run_in_executor(None, ai_handler.chat, persona_id, text, "g%d" % group_id, user_id)
        voice_name = ai_handler.get_voice_for_persona(persona_id)
        if ai_handler.get_voice_reply():
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(random.uniform(2.0, 5.0))  # 模拟真人连续打字
                path = await generate_voice(part, voice_name)
                await send_group_voice(ws, group_id, path)
        else:
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(random.uniform(1.0, 2.5))  # 像真人一样逐条发
                await send_group_message(ws, group_id, part)
        logger.info(f"🤖 群({group_id}) AI回复 [{persona_id}]: {parts[0][:30]}")
    except Exception as exc:
        logger.error(f"🤖 群({group_id}) AI失败: {exc}")
        await send_group_message(ws, group_id, "🤖 AI 暂时不可用，请稍后再试~")


async def handle_ai_private(ws, user_id: int, text: str, persona_override: str = None, speaker_id: int = 0):
    """私聊 AI 语音回复（可能连续发多条，模拟真人节奏）"""
    persona_id = persona_override or ai_handler.get_current_persona()
    if not persona_id:
        await send_private_message(ws, user_id, ai_persona_text())
        return
    if ai_handler.get_affection(persona_id, "p%d" % user_id, speaker_id or user_id) <= 0:
        return  # 好感度为 0：不回复说话人
    try:
        loop = asyncio.get_running_loop()
        parts = await loop.run_in_executor(None, ai_handler.chat, persona_id, text, "p%d" % user_id, speaker_id or user_id)
        voice_name = ai_handler.get_voice_for_persona(persona_id)
        if ai_handler.get_voice_reply():
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(random.uniform(2.0, 5.0))  # 模拟真人连续打字
                path = await generate_voice(part, voice_name)
                await send_private_voice(ws, user_id, path)
        else:
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(random.uniform(1.0, 2.5))  # 像真人一样逐条发
                await send_private_message(ws, user_id, part)
        logger.info(f"🤖 私聊({user_id}) AI回复 [{persona_id}]: {parts[0][:30]}")
    except Exception as exc:
        logger.error(f"🤖 私聊({user_id}) AI失败: {exc}")
        await send_private_message(ws, user_id, "🤖 AI 暂时不可用，请稍后再试~")


# ── AI 请求队列（应对短时间多人询问） ──
_ai_queue = asyncio.Queue()


async def ai_enqueue(ws, target_id, text, persona_override, is_group, user_id):
    """AI 任务入队；返回前面排队的条数，队列已满返回 -1"""
    qmax = ai_handler.get_queue_max()
    if _ai_queue.qsize() >= qmax:
        return -1
    ahead = _ai_queue.qsize()
    await _ai_queue.put((ws, target_id, text, persona_override, is_group, user_id))
    return ahead


async def ai_worker():
    """串行处理 AI 队列（语音合成本来就是单线程，FIFO 保证公平不乱序）"""
    while True:
        ws, target_id, text, persona_override, is_group, user_id = await _ai_queue.get()
        try:
            if is_group:
                await handle_ai_group(ws, target_id, text, persona_override, user_id)
            else:
                await handle_ai_private(ws, target_id, text, persona_override, user_id)
        except Exception as exc:
            logger.error(f"🤖 AI 队列任务失败: {exc}")


def ai_dispatch(ws, target_id, text, persona_override, is_group, user_id, reply_fn):
    """AI 统一入口：入队 + 过载拒绝"""
    async def _do():
        ahead = await ai_enqueue(ws, target_id, text, persona_override, is_group, user_id)
        if ahead < 0:
            await reply_fn("🤖 消息太多啦，等我说完这一波再找我吧~")
    asyncio.create_task(_do())


async def handle_aff_group(ws, group_id: int, user_id: int, arg_str: str):
    """群聊好感度：/aff | /aff rank | /aff set <QQ> <0-100> | /aff reset <QQ|all>"""
    persona_id = ai_handler.get_current_persona()
    if not persona_id:
        await send_group_message(ws, group_id, "🤖 请先设置人设再使用好感度功能（/persona <人设>）")
        return
    conv = "g%d" % group_id
    args = arg_str.split()
    cmd = args[1] if len(args) > 1 else None

    if cmd is None:
        val = ai_handler.get_affection(persona_id, conv, user_id)
        await send_group_message(ws, group_id, f"💗 「{persona_id}」对你的好感度：{val}")
        return

    if cmd in ("rank", "list"):
        items = ai_handler.get_affection_rank(persona_id, conv)
        if not items:
            await send_group_message(ws, group_id, "💗 还没有好感度记录~")
            return
        lines = [f"💗 「{persona_id}」好感度排行："]
        for i, (qq, v) in enumerate(items[:20], 1):
            lines.append(f"  {i}. {qq}：{v}")
        await send_group_message(ws, group_id, "\n".join(lines))
        return

    if cmd in ("set", "reset"):
        if user_id not in config.VOICE_CONTROL_USERS:
            await send_group_message(ws, group_id, "⛔ 只有管理员可以设置好感度~")
            return
        if cmd == "set":
            if len(args) >= 4 and args[2].isdigit() and args[3].isdigit():
                ai_handler.set_affection(persona_id, conv, int(args[2]), int(args[3]))
                await send_group_message(ws, group_id, f"✅ 已将 {args[2]} 在「{persona_id}」下的好感度设为 {args[3]}")
            else:
                await send_group_message(ws, group_id, "用法: /aff set <QQ> <0-100>")
        else:
            if len(args) >= 3 and args[2] == "all":
                ai_handler.reset_affection_all(persona_id, conv)
                await send_group_message(ws, group_id, f"✅ 已重置全群在「{persona_id}」下的好感度（回到50）")
            elif len(args) >= 3 and args[2].isdigit():
                ai_handler.reset_affection(persona_id, conv, int(args[2]))
                await send_group_message(ws, group_id, f"✅ 已重置 {args[2]} 在「{persona_id}」下的好感度（回到50）")
            else:
                await send_group_message(ws, group_id, "用法: /aff reset <QQ> 或 /aff reset all")
        return

    await send_group_message(ws, group_id, "用法: /aff | /aff rank | /aff set <QQ> <0-100> | /aff reset <QQ|all>")


async def handle_aff_private(ws, user_id: int, arg_str: str):
    """私聊好感度：/aff | /aff set <0-100> | /aff reset"""
    persona_id = ai_handler.get_current_persona()
    if not persona_id:
        await send_private_message(ws, user_id, "🤖 请先设置人设再使用好感度功能（/persona <人设>）")
        return
    conv = "p%d" % user_id
    args = arg_str.split()
    cmd = args[1] if len(args) > 1 else None
    if cmd is None:
        val = ai_handler.get_affection(persona_id, conv, user_id)
        await send_private_message(ws, user_id, f"💗 「{persona_id}」对你的好感度：{val}")
        return
    if cmd in ("set", "reset"):
        if user_id not in config.VOICE_CONTROL_USERS:
            await send_private_message(ws, user_id, "⛔ 只有管理员可以设置好感度~")
            return
        if cmd == "set":
            if len(args) >= 3 and args[2].isdigit():
                ai_handler.set_affection(persona_id, conv, user_id, int(args[2]))
                await send_private_message(ws, user_id, f"✅ 已把你的好感度设为 {args[2]}")
            else:
                await send_private_message(ws, user_id, "用法: /aff set <0-100>")
        else:
            ai_handler.reset_affection(persona_id, conv, user_id)
            await send_private_message(ws, user_id, "✅ 已重置好感度（回到50）")
        return
    await send_private_message(ws, user_id, "用法: /aff | /aff set <0-100> | /aff reset")


async def handle_group_message(ws, event: dict) -> None:
    group_id = event.get("group_id")
    if group_id not in config.ALLOWED_GROUPS:
        return

    raw_message = event.get("raw_message", "")
    if not raw_message:
        raw_message = "".join(
            seg.get("data", {}).get("text", "")
            for seg in event.get("message", [])
        )

    logger.info(f"📩 群({group_id}): {raw_message[:80]}")

    # ── /help ──
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
    if raw_message.strip().startswith(("/ai ", "/persona")) and not feature_enabled("ai"):
        await send_group_message(ws, group_id, "⛔ AI 功能已由管理员停用~")
        return

    # ── /voice 查看/切换音色 ──
    if raw_message.strip() == "/voice":
        await send_group_message(ws, group_id, voice_list_text())
        return
    if raw_message.strip().startswith("/voice "):
        target = resolve_voice(raw_message.strip()[7:].strip())
        if not target:
            await send_group_message(
                ws, group_id, f"❓ 未知音色，可用: {' / '.join(config.VOICE_NAMES)}"
            )
            return
        if event.get("user_id") not in config.VOICE_CONTROL_USERS:
            await send_group_message(ws, group_id, "⛔ 只有管理员可以切换音色~")
            return
        asyncio.create_task(do_switch_voice(ws, group_id, target, send_group_message))
        return

    # ── /say 语音（支持「/say <音色> <文本>」指定音色） ──
    if raw_message.strip().startswith("/say "):
        rest = raw_message.strip()[5:].strip()
        voice_name = None
        if rest:
            first, _, remain = rest.partition(" ")
            matched = resolve_voice(first)
            if matched:
                voice_name = matched
                rest = remain.strip()
        if rest:
            asyncio.create_task(handle_say_group(ws, group_id, rest, voice_name))
        return

    # ── /sayto 管理员指定 QQ 发送语音 ──
    if raw_message.strip().startswith("/sayto "):
        user_id = event.get("user_id")
        asyncio.create_task(
            handle_sayto_group(ws, group_id, user_id, raw_message.strip()[7:])
        )
        return

    # ── /ai AI语音对话 ──
    if raw_message.strip().startswith("/ai "):
        rest = raw_message.strip()[4:].strip()
        persona = None
        if rest:
            first, _, remain = rest.partition(" ")
            if first in ai_handler.list_personas():
                persona = first
                rest = remain.strip()
        if rest:
            ai_dispatch(ws, group_id, rest, persona, True, event.get("user_id"),
                        lambda m: send_group_message(ws, group_id, m))
        return

    # ── /persona 人设列表/切换 ──
    if raw_message.strip() == "/persona":
        await send_group_message(ws, group_id, ai_persona_text())
        return
    if raw_message.strip().startswith("/persona "):
        if event.get("user_id") not in config.VOICE_CONTROL_USERS:
            await send_group_message(ws, group_id, "⛔ 只有管理员可以切换人设~")
            return
        asyncio.create_task(
            do_switch_persona(ws, group_id, raw_message.strip()[9:].strip(), send_group_message)
        )
        return

    # ── /openvoice /offvoice AI 语音回复开关（仅管理员） ──
    if raw_message.strip() in ("/openvoice", "/offvoice"):
        if event.get("user_id") not in config.VOICE_CONTROL_USERS:
            await send_group_message(ws, group_id, "⛔ 只有管理员可以切换~")
            return
        on = raw_message.strip() == "/openvoice"
        ai_handler.set_voice_reply(on)
        await send_group_message(
            ws, group_id,
            "🎙️ 已开启 AI 语音回复~" if on else "🔇 已关闭 AI 语音回复，改用文字回复~",
        )
        return

    # ── /aff 好感度 ──
    if raw_message.strip().startswith("/aff"):
        asyncio.create_task(
            handle_aff_group(ws, group_id, event.get("user_id"), raw_message.strip())
        )
        return

    # ── /pixiv 插画命令 ──
    if raw_message.strip().startswith("/pixiv "):
        args = raw_message.strip()[7:].strip().split()
        if not args:
            return
        sub_cmd = args[0].lower()
        if sub_cmd in ("rank", "ranking"):
            mode = args[1] if len(args) > 1 else "day"
            asyncio.create_task(handle_pixiv_rank(ws, group_id, mode))
        elif sub_cmd == "search":
            keyword = " ".join(args[1:]) if len(args) > 1 else ""
            if keyword:
                asyncio.create_task(handle_pixiv_search(ws, group_id, keyword))
        elif sub_cmd.isdigit():
            asyncio.create_task(handle_pixiv_download(ws, group_id, sub_cmd))
        return

    # ── /jm 漫画命令（群聊：白名单群内所有人可用）──
    if raw_message.strip().startswith("/jm "):
        user_id = event.get("user_id")
        args = raw_message.strip()[4:].strip().split()
        if not args:
            return
        sub_cmd = args[0].lower()
        comic_id = args[1] if len(args) > 1 else None

        if sub_cmd == "info" and comic_id:
            asyncio.create_task(handle_comic_info(ws, group_id, comic_id))
        elif sub_cmd == "cover" and comic_id:
            asyncio.create_task(handle_comic_cover_group(ws, group_id, comic_id))
        elif sub_cmd in ("rank", "ranking"):
            rank_type = comic_id or "week"
            asyncio.create_task(handle_comic_rank(ws, group_id, rank_type))
        elif sub_cmd.isdigit():
            asyncio.create_task(handle_comic_command(ws, group_id, user_id, sub_cmd))
        return

    # ── AI 被动回复：@机器人 触发（仅白名单群） ──
    if feature_enabled("ai") and ai_handler.get_current_persona():
        self_id = event.get("self_id")
        at_me = False
        for seg in event.get("message", []):
            if seg.get("type") == "at":
                qq = str(seg.get("data", {}).get("qq", ""))
                if qq == str(self_id) or qq == "all":
                    at_me = True
        if at_me:
            clean = re.sub(r"\[CQ:at[^\]]*\]", "", raw_message).strip()
            if clean:
                ai_dispatch(ws, group_id, clean, None, True, event.get("user_id"),
                            lambda m: send_group_message(ws, group_id, m))
                return

    if not feature_enabled("bili"):
        return

    bv_id = extract_bv_from_message(raw_message)
    if not bv_id:
        for seg in event.get("message", []):
            for key in ("url", "text", "content", "data", "meta", "source"):
                val = str(seg.get("data", {}).get(key, ""))
                bv_id = extract_bv_from_message(val)
                if bv_id:
                    break
            if bv_id:
                break
    if not bv_id:
        return

    logger.info(f"🔗 识别到 B站视频: {bv_id}")

    try:
        info = get_video_info(bv_id)
        title = info["title"]
        owner = info["owner"]
        mins, secs = divmod(info["duration"], 60)
        logger.info(f"📋 {title} | UP主: {owner} | {mins}分{secs}秒")

        video_filepath = await download_video(bv_id)
        file_size_mb = os.path.getsize(video_filepath) / (1024 * 1024)
        logger.info(f"✅ 下载完成: {video_filepath} ({file_size_mb:.1f} MB)")

        caption = f"📺 {title}\n👤 UP主：{owner}"
        await send_group_video(ws, group_id, video_filepath, caption)
        logger.info(f"📤 视频 {bv_id} 发送成功")

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"❌ 处理 {bv_id} 时出错: {error_msg}")
        if "文件过大" in error_msg:
            friendly = "😣 视频文件过大（超过 100MB），无法发送到群聊~"
        elif "无法访问" in error_msg or "已被删除" in error_msg:
            friendly = "😣 该视频无法访问，可能已被删除或设置了隐私权限~"
        elif "不可用" in error_msg:
            friendly = "😣 该视频当前不可用，请稍后再试~"
        elif "没有可下载" in error_msg:
            friendly = "😣 暂无可用画质，可能需要登录账号才能下载~"
        else:
            friendly = f"😣 视频处理失败：{error_msg[:100]}\n请稍后再试~"
        await send_group_message(ws, group_id, friendly)


# ----------------------------------------------------------
# 私聊处理：只响应 /jm 命令
# ----------------------------------------------------------

async def handle_private_message(ws, event: dict) -> None:
    user_id = event.get("user_id")
    raw_message = event.get("raw_message", "")

    logger.info(f"📩 私聊({user_id}): {raw_message[:80]}")

    if user_id not in config.COMIC_ALLOWED_USERS:
        return

    msg = raw_message.strip()
    if msg == "/help":
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
    if msg.startswith(("/ai ", "/persona")) and not feature_enabled("ai"):
        await send_private_message(ws, user_id, "⛔ AI 功能已由管理员停用~")
        return

    if msg == "/voice":
        await send_private_message(ws, user_id, voice_list_text())
        return
    if msg.startswith("/voice "):
        target = resolve_voice(msg[7:].strip())
        if not target:
            await send_private_message(
                ws, user_id, f"❓ 未知音色，可用: {' / '.join(config.VOICE_NAMES)}"
            )
        elif user_id not in config.VOICE_CONTROL_USERS:
            await send_private_message(ws, user_id, "⛔ 只有管理员可以切换音色~")
        else:
            asyncio.create_task(
                do_switch_voice(
                    ws, user_id, target,
                    lambda m: send_private_message(ws, user_id, m),
                )
            )
        return

    if msg.startswith("/say "):
        rest = msg[5:].strip()
        voice_name = None
        if rest:
            first, _, remain = rest.partition(" ")
            matched = resolve_voice(first)
            if matched:
                voice_name = matched
                rest = remain.strip()
        if rest:
            asyncio.create_task(handle_say_private(ws, user_id, rest, voice_name))
        return

    if msg.startswith("/sayto "):
        asyncio.create_task(handle_sayto_private(ws, user_id, msg[7:]))
        return

    if msg.startswith("/ai "):
        rest = msg[4:].strip()
        persona = None
        if rest:
            first, _, remain = rest.partition(" ")
            if first in ai_handler.list_personas():
                persona = first
                rest = remain.strip()
        if rest:
            ai_dispatch(ws, user_id, rest, persona, False, user_id,
                        lambda m: send_private_message(ws, user_id, m))
        return

    if msg == "/persona":
        await send_private_message(ws, user_id, ai_persona_text())
        return
    if msg.startswith("/persona "):
        if user_id not in config.VOICE_CONTROL_USERS:
            await send_private_message(ws, user_id, "⛔ 只有管理员可以切换人设~")
        else:
            asyncio.create_task(
                do_switch_persona(
                    ws, user_id, msg[9:].strip(),
                    lambda m: send_private_message(ws, user_id, m),
                )
            )
        return

    if msg in ("/openvoice", "/offvoice"):
        if user_id not in config.VOICE_CONTROL_USERS:
            await send_private_message(ws, user_id, "⛔ 只有管理员可以切换~")
        else:
            on = msg == "/openvoice"
            ai_handler.set_voice_reply(on)
            await send_private_message(
                ws, user_id,
                "🎙️ 已开启 AI 语音回复~" if on else "🔇 已关闭 AI 语音回复，改用文字回复~",
            )
        return

    if msg.startswith("/aff"):
        asyncio.create_task(handle_aff_private(ws, user_id, msg.strip()))
        return

    if msg.startswith("/pixiv "):
        args = msg[7:].strip().split()
        if not args:
            return
        sub_cmd = args[0].lower()
        if sub_cmd in ("rank", "ranking"):
            mode = args[1] if len(args) > 1 else "day"
            items = await ranking_illust_with_thumbs(mode)
            if not items:
                await send_private_message(ws, user_id, "暂无数据")
            else:
                title = {"day": "📊 日榜", "week": "📊 周榜", "month": "📊 月榜"}.get(mode, f"📊 {mode}")
                await send_pixiv_forward(ws, user_id, items, title, False)
        elif sub_cmd == "search":
            keyword = " ".join(args[1:]) if len(args) > 1 else ""
            if keyword:
                items = await search_illust_with_thumbs(keyword)
                if not items:
                    await send_private_message(ws, user_id, f"🔍 未找到「{keyword}」相关插画")
                else:
                    await send_pixiv_forward(ws, user_id, items, f"🔍 搜索「{keyword}」结果", False)
        elif sub_cmd.isdigit():
            await handle_pixiv_download_private(ws, user_id, sub_cmd)
        return

    if msg.startswith("/jm "):
        args = msg[4:].strip().split()
        if not args:
            return
        sub_cmd = args[0].lower()
        comic_id = args[1] if len(args) > 1 else None

        if sub_cmd == "info" and comic_id:
            info_text = await get_album_info(comic_id)
            await send_private_message(ws, user_id, info_text)
        elif sub_cmd == "cover" and comic_id:
            await handle_comic_cover_private(ws, user_id, comic_id)
        elif sub_cmd in ("rank", "ranking"):
            rank_type = comic_id or "month"
            rank_text = await get_ranking(rank_type)
            await send_private_message(ws, user_id, rank_text)
        elif sub_cmd.isdigit():
            await handle_comic_private(ws, user_id, sub_cmd)

    # ── AI 被动回复：私聊白名单用户直接对话 ──
    if feature_enabled("ai"):
        if msg:
            ai_dispatch(ws, user_id, msg, None, False, user_id,
                        lambda m: send_private_message(ws, user_id, m))
            return


async def send_private_message(ws, user_id: int, message: str) -> None:
    await ws.send(json.dumps({
        "action": "send_private_msg",
        "params": {"user_id": user_id, "message": message},
    }))


async def handle_say_group(ws, group_id: int, text: str, voice_name: str = None):
    """群聊 /say <文本> — 语音条（可指定音色）"""
    try:
        if len(text) > VOICE_MAX_CHARS:
            await send_group_message(
                ws, group_id, f"🎙️ 文本太长了，请控制在 {VOICE_MAX_CHARS} 字以内~"
            )
            return
        await send_group_message(ws, group_id, "🎙️ 正在合成语音，请稍候...")
        path = await generate_voice(text, voice_name)
        await send_group_voice(ws, group_id, path)
        logger.info(f"🎙️ 群({group_id}) 语音发送成功: {text[:30]}")
    except Exception as exc:
        logger.error(f"🎙️ 群({group_id}) 语音失败: {exc}")
        await send_group_message(ws, group_id, "🎙️ 语音服务暂时不可用，请稍后再试~")


async def handle_say_private(ws, user_id: int, text: str, voice_name: str = None):
    """私聊 /say <文本> — 语音条（可指定音色）"""
    try:
        if len(text) > VOICE_MAX_CHARS:
            await send_private_message(
                ws, user_id, f"🎙️ 文本太长了，请控制在 {VOICE_MAX_CHARS} 字以内~"
            )
            return
        await send_private_message(ws, user_id, "🎙️ 正在合成语音，请稍候...")
        path = await generate_voice(text, voice_name)
        await send_private_voice(ws, user_id, path)
        logger.info(f"🎙️ 私聊({user_id}) 语音发送成功: {text[:30]}")
    except Exception as exc:
        logger.error(f"🎙️ 私聊({user_id}) 语音失败: {exc}")
        await send_private_message(ws, user_id, "🎙️ 语音服务暂时不可用，请稍后再试~")


async def _do_sayto(ws, sender_id: int, target_qq: int, text: str, reply_fn):
    """核心逻辑：管理员指定 QQ 发送洛琪希语音"""
    if sender_id not in config.VOICE_CONTROL_USERS:
        await reply_fn("⛔ 你没有使用该命令的权限~")
        return
    if len(text) > VOICE_MAX_CHARS:
        await reply_fn(f"🎙️ 文本太长了，请控制在 {VOICE_MAX_CHARS} 字以内~")
        return
    try:
        await reply_fn(f"🎙️ 正在给 {target_qq} 合成语音...")
        path = await generate_voice(text)
        await send_private_voice(ws, target_qq, path)
        logger.info(f"🎙️ 管理员 {sender_id} 指定发语音给 {target_qq}: {text[:30]}")
        await reply_fn(f"✅ 语音已发送给 {target_qq}")
    except Exception as exc:
        logger.error(f"🎙️ /sayto 失败 (目标 {target_qq}): {exc}")
        await reply_fn("🎙️ 发送失败：对方可能不是好友/未开启私聊，或语音服务不可用~")


async def handle_sayto_group(ws, group_id: int, sender_id: int, arg_str: str):
    parts = arg_str.strip().split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        await send_group_message(ws, group_id, "🎙️ 用法: /sayto <QQ号> <文本>")
        return
    reply_fn = lambda msg: send_group_message(ws, group_id, msg)
    await _do_sayto(ws, sender_id, int(parts[0]), parts[1].strip(), reply_fn)


async def handle_sayto_private(ws, sender_id: int, arg_str: str):
    parts = arg_str.strip().split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        await send_private_message(ws, sender_id, "🎙️ 用法: /sayto <QQ号> <文本>")
        return
    reply_fn = lambda msg: send_private_message(ws, sender_id, msg)
    await _do_sayto(ws, sender_id, int(parts[0]), parts[1].strip(), reply_fn)


async def handle_comic_private(ws, user_id: int, comic_id: str):
    logger.info(f"📚 私聊漫画请求: user={user_id}, id={comic_id}")
    try:
        await send_private_message(ws, user_id, f"📚 正在下载漫画 {comic_id}，请稍候...")

        pdf_path = await download_comic(comic_id)

        pdf_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if pdf_size_mb > COMIC_MAX_PDF_SIZE:
            await send_private_message(ws, user_id, f"😣 漫画 PDF 过大（{pdf_size_mb:.1f}MB），无法发送~")
            return

        logger.info(f"📚 漫画 PDF: {pdf_path} ({pdf_size_mb:.1f} MB)")

        # 用消息段格式发送文件（OneBot v11 标准方式）
        abs_path = os.path.abspath(pdf_path).replace("\\", "/")
        filename = os.path.basename(pdf_path).replace('.pdf.pdf', '.pdf')
        await ws.send(json.dumps({
            "action": "send_private_msg",
            "params": {
                "user_id": user_id,
                "message": [
                    {"type": "text", "data": {"text": f"📚 {filename}"}},
                    {"type": "file", "data": {"file": f"file://{abs_path}", "name": filename}},
                ],
            },
        }))
        logger.info(f"📤 漫画 {comic_id} 发送成功")

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"❌ 漫画 {comic_id} 失败: {error_msg}")
        await send_private_message(ws, user_id, f"😣 漫画下载失败：{error_msg[:100]}")


async def handle_comic_info(ws, group_id: int, comic_id: str):
    """群聊 /jm info <id> — 查看漫画详情"""
    try:
        info_text = await get_album_info(comic_id)
        await send_group_message(ws, group_id, info_text)
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 获取失败: {e}")


async def handle_comic_cover_group(ws, group_id: int, comic_id: str):
    """群聊 /jm cover <id> — 发送封面"""
    try:
        from config import TEMP_DIR
        cover_path = await download_cover(comic_id, TEMP_DIR)
        abs_path = os.path.abspath(cover_path).replace("\\", "/")
        await ws.send(json.dumps({
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": [
                    {"type": "text", "data": {"text": f"📖 JM{comic_id} 封面"}},
                    {"type": "image", "data": {"file": f"file://{abs_path}"}},
                ],
            },
        }))
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 封面获取失败: {e}")


async def handle_comic_cover_private(ws, user_id: int, comic_id: str):
    """私聊 /jm cover <id>"""
    try:
        from config import TEMP_DIR
        cover_path = await download_cover(comic_id, TEMP_DIR)
        abs_path = os.path.abspath(cover_path).replace("\\", "/")
        await ws.send(json.dumps({
            "action": "send_private_msg",
            "params": {
                "user_id": user_id,
                "message": [
                    {"type": "text", "data": {"text": f"📖 JM{comic_id} 封面"}},
                    {"type": "image", "data": {"file": f"file://{abs_path}"}},
                ],
            },
        }))
    except Exception as e:
        await send_private_message(ws, user_id, f"😣 封面获取失败: {e}")


async def handle_comic_rank(ws, group_id: int, rank_type: str):
    """ /jm rank [day|week|month] — 查看排行榜"""
    try:
        rank_text = await get_ranking(rank_type)
        await send_group_message(ws, group_id, rank_text)
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 排行榜获取失败: {e}")


# ── Pixiv 命令处理 ──

async def send_pixiv_forward(ws, target_id: int, items: list[dict], title: str, is_group: bool):
    """用合并转发消息发送搜索结果（文字+缩略图）"""
    if not items:
        return

    # 第一段：文字摘要
    summary_lines = [title, ""]
    for i, item in enumerate(items, 1):
        summary_lines.append(f"  {i:>2}. [{item['id']}] {item['title'][:25]} | ✏️{item['author']}")
    summary_lines.append("")
    summary_lines.append("回复 /pixiv <ID> 下载原图")

    # 构建转发节点：摘要 + 每个插图一个节点
    messages = [
        {"type": "node", "data": {"name": "PixivBot", "uin": "YOUR_BOT_QQ",
         "content": "\n".join(summary_lines)}}
    ]

    for item in items:
        if item.get("local_path"):
            abs_path = os.path.abspath(item["local_path"]).replace("\\", "/")
            content = [
                {"type": "text", "data": {"text": f"[{item['id']}] {item['title'][:30]}\n✏️{item['author']}"}},
                {"type": "image", "data": {"file": f"file://{abs_path}"}},
            ]
        else:
            content = f"[{item['id']}] {item['title'][:30]}\n✏️{item['author']}"
        messages.append({"type": "node", "data": {"name": "PixivBot", "uin": "YOUR_BOT_QQ", "content": content}})

    action = "send_group_forward_msg" if is_group else "send_private_forward_msg"
    target_key = "group_id" if is_group else "user_id"
    await ws.send(json.dumps({"action": action, "params": {target_key: target_id, "messages": messages}}))


async def handle_pixiv_search(ws, group_id: int, keyword: str):
    try:
        items = await search_illust_with_thumbs(keyword)
        if not items:
            await send_group_message(ws, group_id, f"🔍 未找到「{keyword}」相关插画")
            return
        await send_pixiv_forward(ws, group_id, items, f"🔍 搜索「{keyword}」结果", True)
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 Pixiv搜索失败: {e}")


async def handle_pixiv_rank(ws, group_id: int, mode: str):
    try:
        items = await ranking_illust_with_thumbs(mode)
        if not items:
            await send_group_message(ws, group_id, "📊 暂无数据")
            return
        title = {"day": "📊 日榜", "week": "📊 周榜", "month": "📊 月榜"}.get(mode, f"📊 {mode}")
        await send_pixiv_forward(ws, group_id, items, title, True)
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 Pixiv排行榜失败: {e}")

async def handle_pixiv_download(ws, group_id: int, illust_id: str):
    try:
        await send_group_message(ws, group_id, f"🎨 正在下载插画 {illust_id}...")
        path = await download_illust_img(illust_id)
        abs_path = os.path.abspath(path).replace("\\", "/")
        await ws.send(json.dumps({
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": [
                    {"type": "text", "data": {"text": f"🎨 Pixiv {illust_id}"}},
                    {"type": "image", "data": {"file": f"file://{abs_path}"}},
                ],
            },
        }))
    except Exception as e:
        await send_group_message(ws, group_id, f"😣 下载失败: {e}")

async def handle_pixiv_download_private(ws, user_id: int, illust_id: str):
    try:
        await send_private_message(ws, user_id, f"🎨 正在下载插画 {illust_id}...")
        path = await download_illust_img(illust_id)
        abs_path = os.path.abspath(path).replace("\\", "/")
        await ws.send(json.dumps({
            "action": "send_private_msg",
            "params": {
                "user_id": user_id,
                "message": [
                    {"type": "text", "data": {"text": f"🎨 Pixiv {illust_id}"}},
                    {"type": "image", "data": {"file": f"file://{abs_path}"}},
                ],
            },
        }))
    except Exception as e:
        await send_private_message(ws, user_id, f"😣 下载失败: {e}")


async def heartbeat(ws, interval: int = 30):
    while True:
        await asyncio.sleep(interval)
        try:
            await ws.send(json.dumps({"action": "get_status", "params": {}}))
        except websockets.exceptions.ConnectionClosed:
            break
        except Exception:
            pass


async def config_watch():
    """每 30 秒热加载管理面板修改的配置（白名单/限制/音色参数/功能开关）"""
    while True:
        try:
            config.reload_runtime()
        except Exception as exc:
            logger.error(f"⚙️ 配置热加载失败: {exc}")
        await asyncio.sleep(30)


async def daily_cleanup():
    while True:
        now = datetime.datetime.now()
        target = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        wait = (target - now).total_seconds()
        logger.info(f"🧹 下次清理: {target.strftime('%Y-%m-%d %H:%M:%S')} ({wait/3600:.1f}h)")
        await asyncio.sleep(wait)
        cleanup_temp_dir()
        logger.info("🧹 每日清理完成 (15:00)")


async def listen():
    cleanup_temp_dir()
    logger.info("🧹 已清理遗留临时文件")
    asyncio.create_task(daily_cleanup())
    asyncio.create_task(config_watch())
    asyncio.create_task(ai_worker())

    while True:
        try:
            logger.info(f"🔌 正在连接 NapCatQQ: {NAPCAT_WS_URL}")
            async with websockets.connect(NAPCAT_WS_URL, ping_interval=20, ping_timeout=10, max_size=2**23) as ws:
                logger.info("✅ 已连接到 NapCatQQ，开始监听群消息...")
                hb_task = asyncio.create_task(heartbeat(ws))
                try:
                    async for raw_message in ws:
                        try:
                            event = json.loads(raw_message)
                        except json.JSONDecodeError:
                            continue

                        if event.get("post_type") == "message" and event.get("message_type") == "group":
                            asyncio.create_task(handle_group_message(ws, event))
                        elif event.get("post_type") == "message" and event.get("message_type") == "private":
                            asyncio.create_task(handle_private_message(ws, event))
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("⚠️ WebSocket 断开，重连中...")
                finally:
                    hb_task.cancel()
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError,
                websockets.exceptions.InvalidMessage) as e:
            logger.error(f"❌ 连接失败: {e}，{RECONNECT_DELAY}s 后重试...")
        await asyncio.sleep(RECONNECT_DELAY)


def main():
    print("=" * 50)
    print("  BiliBot Server")
    print(f"  Target: {NAPCAT_WS_URL}")
    print("=" * 50)
    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        logger.info("👋 退出")


if __name__ == "__main__":
    main()
