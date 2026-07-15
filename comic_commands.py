# ============================================================
# 漫画辅助命令：详情 / 封面 / 排行榜
# ============================================================

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2)


def _get_client():
    """获取 jmcomic 客户端"""
    import jmcomic
    return jmcomic.new_downloader().client


def _do_get_album_info(comic_id: str) -> str:
    """获取漫画详情，返回格式化文本"""
    album_id = str(int(comic_id))
    client = _get_client()
    album = client.get_album_detail(album_id)

    lines = [
        f"📖 {album.name}",
        f"🆔 JM{album_id}",
        f"✏️ 作者: {', '.join(album.authors) if album.authors else '未知'}",
        f"🏷 标签: {', '.join(album.tags[:10]) if album.tags else '无'}",
        f"📄 页数: {album.page_count}",
        f"📑 章节: {len(album)} 章",
        f"👁 观看: {int(album.views or 0):,}",
        f"❤️ 喜欢: {int(album.likes or 0):,}",
        f"💬 评论: {album.comment_count}",
        f"📅 发布: {album.pub_date}",
    ]
    if len(album) > 0:
        lines.append("---")
        lines.append(f"📑 章节: {len(album)} 章")
        # 只列章节 ID，不去加载每章详情（page_arr 可能未加载）
        ids = [str(p) if hasattr(p, 'photo_id') else str(getattr(p, 'id', '?'))
               for p in list(album)[:10]]
        lines.append(f"   ID: {', '.join(ids)}")
        if len(album) > 10:
            lines.append(f"  ... 共{len(album)}章")

    return "\n".join(lines)


def _do_download_cover(comic_id: str, save_dir: str) -> str:
    """下载漫画封面，返回文件路径"""
    album_id = str(int(comic_id))
    client = _get_client()
    album = client.get_album_detail(album_id)
    save_path = os.path.join(save_dir, f"JM{album_id}_cover.jpg")
    os.makedirs(save_dir, exist_ok=True)
    client.download_album_cover(album_id, save_path)
    return os.path.abspath(save_path)


def _do_get_ranking(rank_type: str) -> str:
    """获取排行榜，返回格式化文本"""
    from jmcomic import JmModuleConfig, JmMagicConstants

    client = _get_client()
    page_size = JmModuleConfig.PAGE_SIZE_SEARCH

    # day 和 month 有时返回空，降级到 week
    fallback_order = {'day': ['day', 'week'], 'week': ['week'], 'month': ['month', 'week']}
    page = None
    for try_type in fallback_order.get(rank_type, ['week']):
        if try_type == 'day':
            page = client.day_ranking(1)
        elif try_type == 'week':
            page = client.week_ranking(1)
        else:
            page = client.month_ranking(1)
        items = list(page.content) if page and page.content else []
        if items:
            break

    title = {"day": "📊 日排行榜", "week": "📊 周排行榜", "month": "📊 月排行榜"}.get(rank_type, "📊 排行榜")
    if not items:
        return f"{title}\n暂无数据"

    lines = [f"{title}", ""]
    items = list(page.content) if hasattr(page, 'content') and page.content else []
    if not items:
        return f"{title}\n暂无数据"
    for i, item in enumerate(items[:10], 1):
        # content 每项是 tuple: (album_id, {details})
        if isinstance(item, tuple):
            aid, detail = item[0], item[1] if len(item) > 1 else {}
            name = detail.get('name', '?')[:25]
            author = detail.get('author', '?')[:12]
            lines.append(f"  {i:>2}. [{aid}] {name} | ✏️{author}")
        else:
            name = str(getattr(item, 'name', '?'))[:30]
            lines.append(f"  {i:>2}. [{getattr(item,'album_id','?')}] {name}")

    return "\n".join(lines)


async def get_album_info(comic_id: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _do_get_album_info, comic_id)


async def download_cover(comic_id: str, save_dir: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _do_download_cover, comic_id, save_dir)


async def get_ranking(rank_type: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _do_get_ranking, rank_type)
