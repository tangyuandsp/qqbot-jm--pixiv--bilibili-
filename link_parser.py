# ============================================================
# 链接解析模块
# 功能: 从群消息文本中识别 B站视频链接，提取 BV 号
# ============================================================

import re

import requests

from config import BILIBILI_HEADERS

# ----------------------------------------------------------
# 正则定义
# ----------------------------------------------------------

# 长链接: https://www.bilibili.com/video/BV1xx411c7mD 或带参数的 /?spm_id_from=...
_BV_PATTERN = r"BV[a-zA-Z0-9]+"

BILIBILI_LONG_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?bilibili\.com/video/(" + _BV_PATTERN + r")",
    re.IGNORECASE,
)

# 短链接: https://b23.tv/abcd1234
BILIBILI_SHORT_REGEX = re.compile(
    r"https?://b23\.tv/[a-zA-Z0-9]+",
    re.IGNORECASE,
)


def _resolve_short_link(short_url: str) -> str | None:
    """
    跟随 b23.tv 短链接重定向，拿到目标长链接。
    使用 HEAD 请求，只拿 Location 头，避免下载整个页面。

    返回: 长链接 URL 字符串；失败返回 None
    """
    try:
        resp = requests.head(
            short_url,
            headers=BILIBILI_HEADERS,
            allow_redirects=True,
            timeout=10,
        )
        # requests 在 allow_redirects=True 时，resp.url 就是最终地址
        return resp.url
    except requests.RequestException:
        return None


def extract_bv_from_message(text: str) -> str | None:
    """
    从 QQ 消息文本中提取 B站视频的 BV 号。

    优先级:
      1. 直接匹配长链接 (bilibili.com/video/BVxxxx)
      2. 匹配短链接 (b23.tv/xxxx)，跟随重定向后再提取

    参数:
        text: 群消息原文 (raw_message)

    返回:
        BV 号字符串，如 "BV1xx411c7mD"；未匹配到返回 None
    """
    # ── 预处理：还原 QQ JSON 卡片中被转义的斜杠 ──
    # 例如 https:\/\/b23.tv\/xxx → https://b23.tv/xxx
    text = text.replace(r"\/", "/")
    text = text.replace("&#47;", "/")

    # ── 第 1 步: 先尝试长链接 ──
    match = BILIBILI_LONG_REGEX.search(text)
    if match:
        return match.group(1)

    # ── 第 2 步: 尝试短链接 ──
    short_match = BILIBILI_SHORT_REGEX.search(text)
    if short_match:
        short_url = short_match.group(0)
        final_url = _resolve_short_link(short_url)
        if final_url:
            # 从重定向后的长 URL 中提取 BV 号
            bv_match = BILIBILI_LONG_REGEX.search(final_url)
            if bv_match:
                return bv_match.group(1)

    return None
