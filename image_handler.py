# -*- coding: utf-8 -*-
"""AI 绘图模块（火山方舟 Seedream 文生图 / 图生图）

- generate_image(prompt, ref_image_bytes=None) -> (本地文件路径, 模型名)
- 模型链式兜底：优先 Seedream 4.5（200 张免费额度），
  额度用尽 / 限流 / 报错时自动换下一个模型（config.SEEDREAM_MODELS）
- 图生图：传入引用图字节，自动走 `image` 参数（data URL）
"""
import base64
import json
import logging
import os
import time
import urllib.request
import urllib.error

import requests

import config

logger = logging.getLogger("BiliBot")


def _ensure_tmp() -> None:
    os.makedirs(config.DRAW_TEMP_DIR, exist_ok=True)


def _call_once(model_cfg: dict, prompt: str, ref_b64: str | None) -> str:
    """调用单个模型，返回图片下载 URL。失败抛异常。"""
    body = {
        "model": model_cfg["id"],
        "prompt": prompt,
        "size": model_cfg.get("size", "2048x2048"),
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
    """内容审核类报错：换模型也没用，直接终止链式重试。"""
    low = (msg or "").lower()
    return (
        ("content" in low and ("filter" in low or "sensitive" in low))
        or "sensitive" in low
        or "审" in low
        or "敏感" in low
        or "违规" in low
    )


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
    last_err = ""
    for cfg in config.SEEDREAM_MODELS:
        retried_content = False
        while True:
            try:
                url = _call_once(cfg, prompt, ref_b64)
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
                    # 内容审核偶发抖动：同模型重试一次；仍失败则立即终止（换模型没用）
                    if not retried_content:
                        retried_content = True
                        logger.info("🎨 [%s] 内容审核偶发拦截，重试一次", cfg["label"])
                        continue
                    logger.warning("🎨 模型 [%s] 内容审核: %s", cfg["label"], last_err)
                    raise RuntimeError("CONTENT: " + last_err)
                logger.warning("🎨 模型 [%s] 失败: %s", cfg["label"], last_err)
                break  # 非内容错误，换下一个模型
            except Exception as exc:
                last_err = str(exc)
                logger.warning("🎨 模型 [%s] 异常: %s", cfg["label"], exc)
                break
    raise RuntimeError(last_err or "图片生成失败")


if __name__ == "__main__":
    # 本地自测：python3 image_handler.py "<提示词>"
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "一只橘猫坐在樱花树下"
    print(generate_image(p))
