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
from config import (
    ALLOWED_GROUPS,
    COMIC_ALLOWED_USERS,
    COMIC_MAX_PDF_SIZE,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    NAPCAT_WS_URL,
    RECONNECT_DELAY,
)
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

async def handle_group_message(ws, event: dict) -> None:
    group_id = event.get("group_id")
    if group_id not in ALLOWED_GROUPS:
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

    if user_id not in COMIC_ALLOWED_USERS:
        return

    msg = raw_message.strip()
    if msg == "/help":
        await send_private_message(ws, user_id, HELP)
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


async def send_private_message(ws, user_id: int, message: str) -> None:
    await ws.send(json.dumps({
        "action": "send_private_msg",
        "params": {"user_id": user_id, "message": message},
    }))


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
        {"type": "node", "data": {"name": "PixivBot", "uin": "3421767135",
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
        messages.append({"type": "node", "data": {"name": "PixivBot", "uin": "3421767135", "content": content}})

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
