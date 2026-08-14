# -*- coding: utf-8 -*-
"""本地 Stable Diffusion 绘图模块（服务器侧）

通过 SSH 反向隧道调用本地 Windows 上的 Stable Diffusion WebUI API
（本地跑 local_draw_daemon.py 建立 服务器17860 → 本地7860 隧道）。

- generate_image(prompt, ref_image_bytes) -> (本地文件路径, 模型名)
- 触发：提示词含「本地」时由 main.py 路由到本模块
- 走 img2img：保持原图比例，降噪强度控制改动幅度
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

MAX_SIDE = 768  # SD1.5 在 6GB 显存上的安全出图边长


def _ensure_tmp() -> None:
    os.makedirs(config.LOCAL_DRAW_TEMP_DIR, exist_ok=True)


def _sd_api(path: str, body: dict | None = None, timeout: float = 300):
    url = config.LOCAL_SD_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if body else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"本地SD HTTP {exc.code}: {exc.read().decode('utf-8', 'ignore')[:200]}")


def _pick_checkpoint() -> str:
    """选 checkpoint：优先配置里指定的，否则用第一个可用的。"""
    try:
        models = _sd_api("/sdapi/v1/sd-models", timeout=30)
        if not models:
            return ""
        names = [m.get("model_name", "") for m in models]
        pref = config.LOCAL_SD_CHECKPOINT
        if pref:
            pref_base = pref.rsplit(".", 1)[0].lower()
            for n in names:
                if pref.lower() in n.lower() or pref_base in n.lower():
                    return n
        return names[0]
    except Exception as exc:
        logger.warning("🖥️ 获取本地SD模型列表失败: %s", exc)
        return config.LOCAL_SD_CHECKPOINT or ""


def _prep_init(img_bytes: bytes):
    """缩放参考图到安全尺寸，返回 (base64, width, height)。"""
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    w, h = img.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        w, h = int(w * scale), int(h * scale)
    w -= w % 2
    h -= h % 2
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, max(1, w), max(1, h)


def generate_image(prompt: str, ref_image_bytes: bytes | None = None):
    """本地 SD 图生图，返回 (本地文件路径, 模型名)。失败抛异常。"""
    if not ref_image_bytes:
        raise RuntimeError("本地SD仅支持图生图（需引用图片）")
    _ensure_tmp()
    init_b64, width, height = _prep_init(ref_image_bytes)
    checkpoint = _pick_checkpoint()

    body = {
        "init_images": [f"data:image/jpeg;base64,{init_b64}"],
        "prompt": f"{prompt}, masterpiece, best quality, highly detailed, anime",
        "negative_prompt": "EasyNegativeV2, lowres, bad anatomy, bad hands, worst quality, low quality, watermark",
        "steps": 25,
        "cfg_scale": 7.0,
        "width": width,
        "height": height,
        "denoising_strength": 0.68,
        "sampler_name": "DPM++ 2M Karras",
        "seed": -1,
    }
    if checkpoint:
        body["override_settings"] = {"sd_model_checkpoint": checkpoint}

    resp = _sd_api("/sdapi/v1/img2img", body, timeout=300)
    images = resp.get("images") or []
    if not images:
        raise RuntimeError("本地SD未返回图片")
    raw = images[0]
    if "," in raw:
        raw = raw.split(",", 1)[1]
    data = base64.b64decode(raw)
    path = os.path.join(
        config.LOCAL_DRAW_TEMP_DIR, f"local_{int(time.time() * 1000)}.png"
    )
    with open(path, "wb") as f:
        f.write(data)
    label = f"本地SD({os.path.basename(checkpoint).split('.')[0][:12]})" if checkpoint else "本地SD"
    logger.info("🖥️ 本地SD生成成功 -> %s (%d KB)", path, os.path.getsize(path) // 1024)
    return path, label


if __name__ == "__main__":
    # 自测：python3 local_draw_handler.py <图片路径> "<提示词>"
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else None
    q = sys.argv[2] if len(sys.argv) > 2 else "把头发染成粉色"
    with open(p, "rb") as f:
        print(generate_image(q, f.read()))
