# ============================================================
# 视频信息模块
# 功能: 通过 B站公开 API 获取视频元数据（标题、UP主、时长）
# ============================================================

import requests

from config import BILIBILI_HEADERS


def get_video_info(bv_id: str) -> dict:
    """
    调用 B站公开 API 获取视频基本信息。

    API 文档参考:
      https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/video/info.md

    参数:
        bv_id: 视频 BV 号，如 "BV1xx411c7mD"

    返回:
        {
            "title":    "视频标题",
            "owner":    "UP主昵称",
            "bvid":     "BV号",
            "duration": 视频总秒数 (int),
            "desc":     "视频简介",
        }

    异常:
        RuntimeError — API 返回非 0 状态码
        requests.RequestException — 网络错误
    """
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"

    resp = requests.get(url, headers=BILIBILI_HEADERS, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(
            f"B站 API 返回错误 (code={data['code']}): {data.get('message', '未知错误')}"
        )

    video_data = data["data"]
    return {
        "title": video_data["title"],
        "owner": video_data["owner"]["name"],
        "bvid": bv_id,
        "duration": video_data.get("duration", 0),
        "desc": video_data.get("desc", ""),
    }
