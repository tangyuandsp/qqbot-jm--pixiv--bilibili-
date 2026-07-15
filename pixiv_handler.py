# ============================================================
# Pixiv 插画功能模块（curl 后端，避免 Python SSL 问题）
# ============================================================

import asyncio
import json
import os
import re
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=1)
_img_executor = ThreadPoolExecutor(max_workers=3)  # 缩略图并行下载
_OUT_DIR = "/opt/bilibot/temp_videos/pixiv"

PROXY = "http://127.0.0.1:10091"
TOKEN = ""
TOKEN_FILE = "/tmp/pixiv_token.json"


def _curl_get(url: str, headers: dict = None) -> dict:
    """通过 curl + 代理 请求 Pixiv API"""
    cmd = ["curl", "-s", "-x", PROXY, "--connect-timeout", "15", "--max-time", "20"]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr[:100]}")
    data = json.loads(result.stdout)
    if "error" in data:
        raise RuntimeError(f"API error: {data}")
    return data


def _get_token():
    global TOKEN
    import time
    from config import PIXIV_REFRESH_TOKEN

    # 尝试缓存
    if TOKEN and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                cache = json.load(f)
                if cache.get("expires", 0) > time.time() + 60:
                    TOKEN = cache["token"]
                    return TOKEN
        except Exception:
            pass

    data = _curl_post(
        "https://oauth.secure.pixiv.net/auth/token",
        {
            "client_id": "MOBrBDS8blbauoSck0ZfDbtuzpyT",
            "client_secret": "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj",
            "grant_type": "refresh_token",
            "refresh_token": PIXIV_REFRESH_TOKEN,
        },
    )
    TOKEN = data["access_token"]
    expires = time.time() + data.get("expires_in", 3600)
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": TOKEN, "expires": expires}, f)
    except Exception:
        pass
    return TOKEN


def _curl_post(url: str, data: dict) -> dict:
    cmd = ["curl", "-s", "-x", PROXY, "--connect-timeout", "15", "--max-time", "20"]
    for k, v in data.items():
        cmd += ["-d", f"{k}={v}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr[:100]}")
    return json.loads(result.stdout)


def _do_search(keyword: str) -> list[dict]:
    token = _get_token()
    data = _curl_get(
        f"https://app-api.pixiv.net/v1/search/illust?word={urllib.parse.quote(keyword)}",
        {"Authorization": f"Bearer {token}"},
    )
    items = []
    for illust in data.get("illusts", [])[:10]:
        items.append({
            "id": str(illust["id"]),
            "title": illust["title"],
            "author": illust["user"]["name"],
            "url": illust.get("image_urls", {}).get("square_medium", ""),
        })
    return items


def _do_ranking(mode: str = "day") -> list[dict]:
    token = _get_token()
    data = _curl_get(
        f"https://app-api.pixiv.net/v1/illust/ranking?mode={mode}",
        {"Authorization": f"Bearer {token}"},
    )
    items = []
    for illust in data.get("illusts", [])[:10]:
        items.append({
            "id": str(illust["id"]),
            "title": illust["title"],
            "author": illust["user"]["name"],
            "url": illust.get("image_urls", {}).get("square_medium", ""),
        })
    return items


def _do_download_illust(illust_id: str) -> str:
    token = _get_token()
    data = _curl_get(
        f"https://app-api.pixiv.net/v1/illust/detail?illust_id={illust_id}",
        {"Authorization": f"Bearer {token}"},
    )
    illust = data["illust"]
    os.makedirs(_OUT_DIR, exist_ok=True)

    image_url = illust.get("meta_single_page", {}).get("original_image_url")
    if not image_url:
        image_url = illust.get("image_urls", {}).get("large")
    if not image_url:
        image_url = illust.get("image_urls", {}).get("medium")

    # 把 i.pximg.net 替换为 i.pixiv.re 代理（pixiv 图片反代）
    image_url = image_url.replace("i.pximg.net", "i.pixiv.re")

    safe_title = re.sub(r'[\\/:*?"<>|]', '_', illust["title"][:30])
    name = f"pixiv_{illust_id}_{safe_title}.jpg"
    path = os.path.join(_OUT_DIR, name)

    # 用代理下载（i.pixiv.re 是反代，也可能被墙）
    subprocess.run(
        ["curl", "-s", "-L", "-x", PROXY, "-o", path,
         "-H", "Referer: https://www.pixiv.net/",
         image_url],
        timeout=30,
    )
    return os.path.abspath(path)


async def search_illust(keyword: str) -> str:
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(_executor, _do_search, keyword)
    if not items:
        return f"🔍 未找到「{keyword}」相关插画"
    lines = [f"🔍 搜索「{keyword}」结果 TOP10:", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i:>2}. [{item['id']}] {item['title'][:25]} | ✏️{item['author']}")
    lines.append("")
    lines.append("回复 /pixiv <ID> 下载该插画")
    return "\n".join(lines)


async def ranking_illust(mode: str = "day") -> str:
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(_executor, _do_ranking, mode)
    title = {"day": "📊 日榜", "week": "📊 周榜", "month": "📊 月榜"}.get(mode, f"📊 {mode}")
    if not items:
        return f"{title}\n暂无数据"
    lines = [f"{title} TOP10:", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i:>2}. [{item['id']}] {item['title'][:25]} | ✏️{item['author']}")
    lines.append("")
    lines.append("回复 /pixiv <ID> 下载该插画")
    return "\n".join(lines)


async def download_illust_img(illust_id: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _do_download_illust, illust_id)


def _download_one_thumb(item: dict) -> dict:
    """下载单张缩略图到本地，返回更新后的 item"""
    url = item.get("url", "")
    if not url:
        return item
    url = url.replace("i.pximg.net", "i.pixiv.re")
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', f"{item['id']}_{item['title'][:20]}")
    path = os.path.join(_OUT_DIR, f"thumb_{safe_name}.jpg")
    os.makedirs(_OUT_DIR, exist_ok=True)
    # 跳过已下载的
    if os.path.exists(path) and os.path.getsize(path) > 100:
        item["local_path"] = path
        return item
    subprocess.run(
        ["curl", "-s", "-L", "-x", PROXY, "-o", path, "--max-time", "20",
         "-H", "Referer: https://www.pixiv.net/", url],
        timeout=25,
    )
    if os.path.exists(path) and os.path.getsize(path) > 100:
        item["local_path"] = path
    return item


def _download_thumbs(items: list[dict]) -> list[dict]:
    """并行下载所有缩略图（最多 3 线程）"""
    from concurrent.futures import as_completed
    if not items:
        return items
    futures = [_img_executor.submit(_download_one_thumb, item) for item in items]
    results = []
    for f in as_completed(futures):
        results.append(f.result())
    # 保持原始顺序
    id_map = {r["id"]: r for r in results}
    return [id_map.get(item["id"], item) for item in items]


async def search_illust_with_thumbs(keyword: str, max_results: int = 10) -> list[dict]:
    """搜索 + 下载缩略图"""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(_executor, _do_search, keyword)
    items = items[:max_results]
    items = await loop.run_in_executor(_img_executor, lambda: _download_thumbs(items))
    return items


async def ranking_illust_with_thumbs(mode: str = "day", max_results: int = 10) -> list[dict]:
    """排行榜 + 下载缩略图"""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(_executor, _do_ranking, mode)
    items = items[:max_results]
    items = await loop.run_in_executor(_img_executor, lambda: _download_thumbs(items))
    return items
