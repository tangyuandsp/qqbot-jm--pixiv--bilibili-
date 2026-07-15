# ============================================================
# 视频下载模块（服务器版）
# 功能: 通过 B站 API 直连获取播放地址，绕过网页 412 风控
# ============================================================

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from config import BILIBILI_HEADERS, MAX_FILE_SIZE, TEMP_DIR

_download_executor = ThreadPoolExecutor(max_workers=2)


def _download_segment(url: str, filepath: str, headers: dict) -> None:
    """流式下载单个视频分段到文件"""
    resp = requests.get(url, headers=headers, stream=True, timeout=60)
    resp.raise_for_status()
    total = 0
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise RuntimeError("视频文件过大，超过群文件发送限制（100MB）")


def _do_download(bv_id: str) -> str:
    """
    通过 B站公开 API 获取播放地址并下载最低画质（无需登录，无需网页解析）。

    流程:
      1. 调 pagelist API 获取 cid
      2. 调 playurl API (qn=16 → 360p) 获取视频直链
      3. 流式下载视频到本地

    参数:
        bv_id: BV 号

    返回:
        下载完成的 .mp4 文件绝对路径
    """
    os.makedirs(TEMP_DIR, exist_ok=True)

    url = f"https://www.bilibili.com/video/{bv_id}"

    # ── 1. 获取 cid ──
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/player/pagelist?bvid={bv_id}",
            headers=BILIBILI_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["code"] != 0:
            raise RuntimeError(f"B站 API 错误: {data.get('message', '未知')}")
        cid = data["data"][0]["cid"]
    except requests.RequestException as e:
        raise RuntimeError(f"获取视频分P信息失败: {e}")

    # ── 2. 获取播放地址（qn=16 → 360p 低画质）──
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bv_id, "cid": cid, "qn": 16, "fnval": 0},
            headers=BILIBILI_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["code"] != 0:
            raise RuntimeError(f"获取播放地址失败: {data.get('message', '未知')}")
        durl = data["data"]["durl"]
        if not durl:
            raise RuntimeError("该视频暂无可用播放源")
        video_url = durl[0]["url"]
    except requests.RequestException as e:
        raise RuntimeError(f"获取播放地址失败: {e}")

    # ── 3. 下载视频文件 ──
    filepath = os.path.join(TEMP_DIR, f"{bv_id}.mp4")

    # 拼上 host 头（有些 CDN 需要）
    download_headers = {
        "User-Agent": BILIBILI_HEADERS["User-Agent"],
        "Referer": "https://www.bilibili.com/",
        "Host": re.search(r"://([^/]+)", video_url).group(1) if "://" in video_url else "",
    }

    try:
        _download_segment(video_url, filepath, download_headers)
    except requests.RequestException as e:
        raise RuntimeError(f"视频下载失败: {e}")

    # 返回
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return os.path.abspath(filepath)
    raise RuntimeError("下载完成但未找到视频文件")


async def download_video(bv_id: str) -> str:
    """异步封装：在线程池中执行同步下载"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_download_executor, _do_download, bv_id)
