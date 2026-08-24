# -*- coding: utf-8 -*-
"""AI 绘图模块（火山方舟 Seedream 文生图 / 图生图）

- generate_image(prompt, ref_image_bytes=None) -> (本地文件路径, 模型名)
- 模型链式兜底：优先 Seedream 4.5（200 张免费额度），
  额度用尽 / 限流 / 报错时自动换下一个模型（config.SEEDREAM_MODELS）
- 图生图：传入引用图字节，自动走 `image` 参数（data URL）
"""
import base64
import io
import json
import logging
import os
import re
import time
import urllib.request
import urllib.error

import requests
from PIL import Image

import config

logger = logging.getLogger("BiliBot")

# 提示词里的显式比例（如 16:9 / 1920x1080 / 竖版 / 方形），命中则按此输出
_RATIO_RE = re.compile(r"(?<!\d)(\d{1,4})\s*[:：xX×]\s*(\d{1,4})(?!\d)")


def _parse_ratio(prompt: str):
    """从提示词解析用户要求的宽高比，返回 (w, h)；没写返回 None。"""
    if not prompt:
        return None
    if re.search(r"方形|正方形|正方", prompt):
        return (1, 1)
    if re.search(r"横版|横屏|横构图", prompt):
        return (16, 9)
    if re.search(r"竖版|竖屏|竖构图", prompt):
        return (9, 16)
    m = _RATIO_RE.search(prompt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if 0 < w <= 10000 and 0 < h <= 10000 and 1 / 16 <= h / w <= 16:
            return (w, h)
    return None


def _compute_size(cfg: dict, ref_image_bytes: bytes | None, prompt: str) -> str:
    """计算输出尺寸：
    - 提示词写了比例 → 按比例
    - 图生图没写比例 → 保持原图比例
    - 文生图没写比例 → 用模型默认尺寸
    """
    min_px = cfg.get("min_px", 3686400)
    max_px = cfg.get("max_px", 16777216)
    ratio = _parse_ratio(prompt)
    if ratio:
        w, h = ratio
    elif ref_image_bytes:
        try:
            img = Image.open(io.BytesIO(ref_image_bytes))
            w, h = img.size
        except Exception:
            w, h = 1, 1
    else:
        return cfg.get("size", "2048x2048")
    if w <= 0 or h <= 0:
        w, h = 1, 1
    # 宽高比限制在 [1/16, 16]
    r = max(1 / 16, min(16, h / w))
    # 以最小总像素为基准，等比放缩到合法范围
    width = max(1, int((min_px / r) ** 0.5))
    height = max(1, int(width * r))
    while width * height < min_px:
        width += 2
        height = max(1, int(width * r))
    while width * height > max_px:
        width -= 2
        height = max(1, int(width * r))
    width -= width % 2
    height -= height % 2
    return f"{max(1, width)}x{max(1, height)}"


def _ensure_tmp() -> None:
    os.makedirs(config.DRAW_TEMP_DIR, exist_ok=True)


def _call_once(model_cfg: dict, prompt: str, ref_b64: str | None, size: str) -> str:
    """调用单个模型，返回图片下载 URL。失败抛异常。"""
    body = {
        "model": model_cfg["id"],
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    if ref_b64:
        body["image"] = f"data:image/jpeg;base64,{ref_b64}"
    req = urllib.request.Request(
        config.ARK_BASE_URL + "/images/generations",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config.ARK_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    url = data["data"][0]["url"]
    if not url:
        raise RuntimeError("接口未返回图片 URL")
    return url


def _is_content_error(msg: str) -> bool:
    """判断是否为内容审核类报错。"""
    low = (msg or "").lower()
    return (
        ("content" in low and ("filter" in low or "sensitive" in low))
        or "sensitive" in low
        or "审" in low
        or "敏感" in low
        or "违规" in low
    )


def _sanitize_ref_image(ref_image_bytes: bytes | None) -> bytes | None:
    """输入图无害化：重编码为 JPEG 并去掉 EXIF。

    内容审核误判可能和图片编码/元数据有关，重编码后重试有机会通过；
    原图内容不改变。失败时原样返回。
    """
    if not ref_image_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(ref_image_bytes))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        return buf.getvalue()
    except Exception:
        return ref_image_bytes


def download_ref_image(image_url: str) -> bytes | None:
    """下载引用图（供图生图用），失败返回 None。"""
    try:
        r = requests.get(
            image_url,
            timeout=30,
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
        return r.content or None
    except Exception as exc:
        logger.error("🎨 引用图下载失败 %s: %s", image_url[:80], exc)
        return None


def generate_image(prompt: str, ref_image_bytes: bytes | None = None):
    """文生图 / 图生图（链式兜底）。

    返回 (本地文件路径, 模型显示名)；所有模型都失败时抛异常。
    """
    _ensure_tmp()
    ref_b64 = base64.b64encode(ref_image_bytes).decode("ascii") if ref_image_bytes else None
    # 审核误拦时的备用图：无害化重编码（去 EXIF）后的版本
    safe_b64 = None
    if ref_image_bytes:
        try:
            safe_bytes = _sanitize_ref_image(ref_image_bytes)
            if safe_bytes and safe_bytes != ref_image_bytes:
                safe_b64 = base64.b64encode(safe_bytes).decode("ascii")
        except Exception:
            safe_b64 = None
    last_err = ""
    content_blocked = False
    for cfg in config.SEEDREAM_MODELS:
        retried_content = False
        while True:
            try:
                size = _compute_size(cfg, ref_image_bytes, prompt)
                url = _call_once(cfg, prompt, ref_b64, size)
                # 下载生成结果到临时目录
                ext = ".png" if url.rstrip().lower().endswith(".png") else ".jpg"
                path = os.path.join(
                    config.DRAW_TEMP_DIR,
                    f"draw_{int(time.time() * 1000)}_{cfg['id'].split('-')[-1]}{ext}",
                )
                urllib.request.urlretrieve(url, path)
                size_kb = os.path.getsize(path) // 1024
                logger.info("🎨 生成成功 [%s] -> %s (%d KB)", cfg["label"], path, size_kb)
                return path, cfg["label"]
            except urllib.error.HTTPError as exc:
                msg = exc.read().decode("utf-8", "ignore")
                try:
                    code = json.loads(msg).get("error", {}).get("code", "")
                except Exception:
                    code = f"HTTP {exc.code}"
                last_err = f"{code}: {msg[:100]}"
                if _is_content_error(msg):
                    content_blocked = True
                    # 内容审核误拦：先用无害化图重试一次；仍失败则换下一个模型
                    if not retried_content:
                        retried_content = True
                        if safe_b64 and safe_b64 != ref_b64:
                            ref_b64 = safe_b64
                            logger.info(
                                "🎨 [%s] 内容审核拦截，用无害化图重试一次", cfg["label"]
                            )
                        else:
                            logger.info("🎨 [%s] 内容审核拦截，重试一次", cfg["label"])
                        continue
                    logger.warning("🎨 模型 [%s] 内容审核: %s", cfg["label"], last_err)
                    break  # 换下一个模型试试（不同模型审核策略可能不同）
                logger.warning("🎨 模型 [%s] 失败: %s", cfg["label"], last_err)
                break  # 非内容错误，换下一个模型
            except Exception as exc:
                last_err = str(exc)
                logger.warning("🎨 模型 [%s] 异常: %s", cfg["label"], exc)
                break
    if content_blocked:
        raise RuntimeError("CONTENT: " + last_err)
    raise RuntimeError(last_err or "图片生成失败")


if __name__ == "__main__":
    # 本地自测：python3 image_handler.py "<提示词>"
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "一只橘猫坐在樱花树下"
    print(generate_image(p))
