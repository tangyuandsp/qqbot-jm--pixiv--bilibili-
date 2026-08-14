# -*- coding: utf-8 -*-
"""图片理解模块（自然对话用）

用途：群里/私聊中，用户引用一条「图片消息」向 bot 提问时，
main.py 调用本模块把图片转成一段中文描述，再连同问题喂给 AI 人设，
让角色「看到了图」并自然地回答，而不是命令式返回一段解析结果。

底层：智谱开放平台 GLM-4V-Flash（免费、稳定、中文好）。
配置：config.ZHIPU_API_KEY / config.ZHIPU_VISION_MODEL
"""
import base64
import io
import json
import logging
import os
import urllib.request

import requests
from PIL import Image

import config

logger = logging.getLogger("BiliBot")

# 图片下载临时目录（用完即删）
VISION_TMP_DIR = os.path.join(config.TEMP_DIR, "vision")
# 下载体积上限（QQ 图片一般几 MB，防御超大图）
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# 缩放边长上限：GLM-4V 对超大图会失败，超过此值先等比缩小
MAX_SIDE = 1024
# 返回给 AI 的描述最长字符数
MAX_DESC_LEN = 220

# 智谱 API（OpenAI 兼容）
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


def _download_image(image_url: str) -> bytes | None:
    """下载 QQ 图片 URL 到内存。失败返回 None。"""
    try:
        r = requests.get(
            image_url,
            timeout=30,
            stream=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": "https://qun.qq.com/",
            },
        )
        r.raise_for_status()
        buf = io.BytesIO()
        size = 0
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                logger.warning("👀 图片过大，放弃: %s", image_url[:80])
                return None
            buf.write(chunk)
        return buf.getvalue() or None
    except Exception as exc:
        logger.error("👀 图片下载失败 %s: %s", image_url[:80], exc)
        return None


def _resize_to_bytes(img_bytes: bytes) -> bytes:
    """等比缩放超大图并转 JPEG，减小请求体积、避免模型失败。"""
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def _call_zhipu(b64: str, question: str) -> str:
    """调用智谱 GLM-4V 理解图片，返回描述文本。"""
    prompt = (
        "请仔细观察这张图片，用简洁的中文（1~3 句话）描述其中的主要内容："
        "主体、场景、画面里出现的文字（如有）。只描述看到的事实，不要猜测，不要评价。"
    )
    if question.strip():
        prompt += f"\n提问者补充的问题：{question.strip()}"
    body = {
        "model": config.ZHIPU_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        ZHIPU_BASE_URL + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.ZHIPU_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return (content or "").strip()


def understand_image_data(img_bytes: bytes, question: str = "") -> str | None:
    """理解内存中的图片字节，返回中文描述；失败返回 None。"""
    try:
        resized = _resize_to_bytes(img_bytes)
        b64 = base64.b64encode(resized).decode("ascii")
        desc = _call_zhipu(b64, question)
        if len(desc) > MAX_DESC_LEN:
            desc = desc[:MAX_DESC_LEN] + "……"
        return desc or None
    except Exception as exc:
        logger.error("👀 图片理解失败: %s", exc)
        return None


def understand_image(image_url: str, question: str = "") -> str | None:
    """下载并理解一张图片 URL，返回中文描述；失败返回 None。"""
    img_bytes = _download_image(image_url)
    if not img_bytes:
        return None
    return understand_image_data(img_bytes, question)


if __name__ == "__main__":
    # 服务器本地自测：python3 vision_handler.py <本地图片路径>
    import sys

    if len(sys.argv) < 2:
        print("用法: python3 vision_handler.py <图片路径>")
        raise SystemExit(1)
    with open(sys.argv[1], "rb") as f:
        raw = f.read()
    print(understand_image_data(raw))
