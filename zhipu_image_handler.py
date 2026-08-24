# -*- coding: utf-8 -*-
"""智谱 cogview 绘图模块（智谱开放平台）

- generate_image(prompt, ref_image_bytes=None) -> (本地文件路径, 模型名)
- 触发：提示词里含「智谱」时，由 main.py 路由到本模块（文生图 / 图生图均可）
- 接口：POST /images/generations，模型 cogview-4
"""
import base64
import io
import json
import logging
import os
import time
import urllib.request
import urllib.error

from PIL import Image

import config

logger = logging.getLogger("BiliBot")

# 参考图最大边长/体积（超过先压缩，防止接口拒绝）
MAX_REF_SIDE = 2048
MAX_REF_BYTES = 8 * 1024 * 1024


def _ensure_tmp() -> None:
    os.makedirs(config.ZHIPU_DRAW_TEMP_DIR, exist_ok=True)


def _mime(img_bytes: bytes) -> str:
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if img_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _prep_ref(img_bytes: bytes):
    """压缩过大的参考图，返回 (bytes, mime)。"""
    mime = _mime(img_bytes)
    if len(img_bytes) <= MAX_REF_BYTES:
        try:
            img = Image.open(io.BytesIO(img_bytes))
            if max(img.size) <= MAX_REF_SIDE:
                return img_bytes, mime
        except Exception:
            return img_bytes, mime
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.thumbnail((MAX_REF_SIDE, MAX_REF_SIDE))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.warning("🖌️ 智谱参考图压缩失败，按原图发送: %s", exc)
        return img_bytes, mime


def generate_image(prompt: str, ref_image_bytes: bytes | None = None):
    """智谱 cogview 文生图 / 图生图，返回 (本地文件路径, 模型名)。失败抛异常。"""
    _ensure_tmp()
    body = {
        "model": config.ZHIPU_DRAW_MODEL,
        "prompt": prompt,
        "size": "1024x1024",
    }
    if ref_image_bytes:
        ref_bytes, mime = _prep_ref(ref_image_bytes)
        b64 = base64.b64encode(ref_bytes).decode("ascii")
        body["image"] = f"data:{mime};base64,{b64}"
    req = urllib.request.Request(
        config.ZHIPU_DRAW_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + config.ZHIPU_DRAW_API_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        url = data["data"][0]["url"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("智谱接口返回格式异常")
    if not url:
        raise RuntimeError("智谱未返回图片 URL")
    ext = ".png" if url.rstrip().lower().endswith(".png") else ".jpg"
    path = os.path.join(
        config.ZHIPU_DRAW_TEMP_DIR, f"zhipu_{int(time.time() * 1000)}{ext}"
    )
    urllib.request.urlretrieve(url, path)
    logger.info("🖌️ 智谱生成成功 -> %s (%d KB)", path, os.path.getsize(path) // 1024)
    return path, "智谱·" + config.ZHIPU_DRAW_MODEL


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "一只橘猫坐在樱花树下"
    print(generate_image(p))
