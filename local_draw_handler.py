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
from ai_secret import DEEPSEEK_API_KEY

logger = logging.getLogger("BiliBot")

MAX_SIDE = config.LOCAL_SD_MAX_SIDE

# DeepSeek 转译 SD 标签的提示词
_SD_TAG_SYSTEM = (
    "你是 Stable Diffusion 提示词翻译助手。把用户的图片修改指令转换成 "
    "SD 可理解的英文标签（逗号分隔），只输出标签本身，不要任何解释、不要加引号、不要加码。"
    "例：把头发染成粉色 → pink hair；换成泳装 → swimsuit, bikini；"
    "去掉衣服 → nude, no clothes, topless；背景改成夜景 → night scene background, city lights。"
    "若指令含比例（16:9、竖版、方形）忽略，只转内容。"
)


def _translate_to_sd_tags(instruction: str) -> str:
    """用 DeepSeek 把中文改图指令转成 SD 英文标签；失败则原样返回。"""
    if not instruction.strip():
        return instruction
    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _SD_TAG_SYSTEM},
            {"role": "user", "content": instruction},
        ],
        "max_tokens": 120,
        "temperature": 0.3,
    }
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + DEEPSEEK_API_KEY,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tags = data["choices"][0]["message"]["content"].strip()
        logger.info("🖥️ 本地SD指令转译: %r -> %r", instruction, tags)
        return tags
    except Exception as exc:
        logger.warning("🖥️ SD 指令转译失败: %s", exc)
        return instruction


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


def _controlnet_model() -> str | None:
    """查 Forge 里已注册的 ControlNet Canny 模型名；没有则返回 None。"""
    try:
        resp = _sd_api("/controlnet/model_list", timeout=20)
        names = resp.get("model_list") or []
        for n in names:
            if "canny" in n.lower() and n != "None":
                return n
    except Exception as exc:
        logger.warning("🖥️ 获取 ControlNet 模型列表失败: %s", exc)
    return None


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
    tags = _translate_to_sd_tags(prompt)
    cn_model = _controlnet_model()

    body = {
        "init_images": [f"data:image/jpeg;base64,{init_b64}"],
        "prompt": f"{tags}, masterpiece, best quality, highly detailed, anime",
        "negative_prompt": "EasyNegativeV2, lowres, bad anatomy, bad hands, worst quality, low quality, watermark",
        "steps": 25,
        "cfg_scale": 7.0,
        "width": width,
        "height": height,
        # ControlNet 锁构图后降噪可低一些：既能换装/换背景，又不会把人物整个换掉
        "denoising_strength": 0.62 if cn_model else 0.72,
        "sampler_name": "DPM++ 2M Karras",
        "seed": -1,
    }
    if checkpoint:
        body["override_settings"] = {"sd_model_checkpoint": checkpoint}
    if cn_model:
        body["alwayson_scripts"] = {
            "controlnet": {
                "args": [
                    {
                        "input_image": f"data:image/jpeg;base64,{init_b64}",
                        "module": "canny",
                        "model": cn_model,
                        "weight": 0.75,
                        "resize_mode": "Crop and Resize",
                        "guidance_start": 0.0,
                        "guidance_end": 0.9,
                    }
                ]
            }
        }

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
