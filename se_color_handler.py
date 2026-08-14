# -*- coding: utf-8 -*-
"""涩涩绘图模块（魔搭 Qwen-Image-Edit，无审核通道）

原「本地SD」通道的替代实现：本地 SD 已弃用，改用阿里魔搭 API-Inference
上托管的开源模型 Qwen/Qwen-Image-Edit（无平台审核层，免费额度）。

- generate_image(prompt, ref_image_bytes) -> (本地文件路径, 模型名)
- 触发：提示词含「涩涩」时由 main.py 路由到本模块（仅支持图生图，需引用图片）
- 调用前用 DeepSeek 把用户指令「包装」成完整编辑指令（保持意图不变），
  失败时用规则模板兜底，尽量让模型准确理解用户想改什么。
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

# 魔搭 API-Inference
MODEL_SCOPE_BASE = "https://api-inference.modelscope.cn"
MODEL_SCOPE_TOKEN = config.MODEL_SCOPE_TOKEN
SE_MODEL = config.SE_MODEL  # "Qwen/Qwen-Image-Edit"
SE_TEMP_DIR = config.SE_TEMP_DIR

# 输入参考图最长边（魔搭对超大图不稳，先等比缩放）
MAX_SIDE = 1536

# 去衣类口语 → 包装表述（保留意图，表达更自然、利于模型理解）
_UNDRESS_KEYWORDS = (
    "去衣", "去掉衣服", "去掉全部衣服", "去掉所有衣服", "去掉一切衣服",
    "把衣服都去掉", "把衣服全去掉", "脱光", "脱掉衣服", "脱掉所有衣服",
    "脱衣服", "全裸", "裸体", "不穿衣服", "移除衣物", "把衣服去掉",
)


def _polish_prompt(instruction: str) -> str:
    """把用户指令「包装」成完整编辑指令（保持最终意图不变）。

    规则式二次加工：去衣类指令换成更自然的表述；其余指令原样保留、
    套入编辑指令模板。不依赖 LLM，稳定可控。
    """
    text = (instruction or "").strip()
    if not text:
        return text
    # 去掉消息解析可能残留的开头标点（如「，去掉所有衣服」）
    text = text.lstrip("，,。;；、 ")
    if any(k in text for k in _UNDRESS_KEYWORDS):
        core = "将图中角色身上所有衣物全部移除，呈现自然健康的人体"
    else:
        core = f"将图中角色的外观按以下要求修改：{text}"
    polished = core + "，保持人物脸部、发型、姿势、背景和原图画风完全不变，高清细节。"
    logger.info("🍑 涩涩提示词包装: %r -> %r", instruction, polished)
    return polished


def _ensure_tmp() -> None:
    os.makedirs(SE_TEMP_DIR, exist_ok=True)


def _prep_image(img_bytes: bytes) -> str:
    """缩放参考图并转 base64 data URL，返回魔搭可直接接收的字符串。"""
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    w, h = img.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        w, h = int(w * scale), int(h * scale)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _submit_task(prompt: str, image_data_url: str, size: str,
                 negative_prompt: str | None = None) -> str:
    """提交异步生成任务，返回 task_id。"""
    body = {"model": SE_MODEL, "prompt": prompt, "size": size, "image": image_data_url}
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    req = urllib.request.Request(
        MODEL_SCOPE_BASE + "/v1/images/generations",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + MODEL_SCOPE_TOKEN,
            "X-ModelScope-Async-Mode": "true",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"魔搭提交失败: {json.dumps(data, ensure_ascii=False)[:300]}")
    return task_id


def _poll_task(task_id: str, max_attempts: int = 60, interval: float = 5.0) -> dict:
    """轮询任务直到 SUCCEED/失败。"""
    for i in range(max_attempts):
        time.sleep(interval)
        req = urllib.request.Request(
            MODEL_SCOPE_BASE + f"/v1/tasks/{task_id}",
            headers={
                "Authorization": "Bearer " + MODEL_SCOPE_TOKEN,
                "Content-Type": "application/json",
                "X-ModelScope-Task-Type": "image_generation",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"魔搭任务查询失败 HTTP {exc.code}")
        status = data.get("task_status")
        if status == "SUCCEED":
            return data
        if status in ("FAILED", "CANCELED", "TIMEOUT"):
            raise RuntimeError(f"魔搭任务失败: {status} {json.dumps(data, ensure_ascii=False)[:200]}")
    raise RuntimeError("魔搭任务超时")


def _size_for(img_bytes: bytes) -> str:
    """按参考图比例给出 size（尽量保留原比例）。"""
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    w, h = img.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        w, h = int(w * scale), int(h * scale)
    w = max(256, w - (w % 16))
    h = max(256, h - (h % 16))
    return f"{w}x{h}"


def generate_image(prompt: str, ref_image_bytes: bytes | None = None):
    """涩涩图生图（魔搭 Qwen-Image-Edit），返回 (本地文件路径, 模型名)。"""
    if not ref_image_bytes:
        raise RuntimeError("涩涩仅支持图生图（需引用图片）")
    if not MODEL_SCOPE_TOKEN:
        raise RuntimeError("魔搭 token 未配置")
    _ensure_tmp()
    polished = _polish_prompt(prompt)
    image_data_url = _prep_image(ref_image_bytes)
    size = _size_for(ref_image_bytes)
    task_id = _submit_task(polished, image_data_url, size)
    data = _poll_task(task_id)
    outputs = data.get("output_images") or []
    if not outputs:
        raise RuntimeError("魔搭未返回图片")
    url = outputs[0] if isinstance(outputs[0], str) else outputs[0].get("url", "")
    if url.startswith("data:"):
        raw = base64.b64decode(url.split(",", 1)[1])
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    path = os.path.join(SE_TEMP_DIR, f"se_{int(time.time() * 1000)}.png")
    with open(path, "wb") as f:
        f.write(raw)
    logger.info("🍑 涩涩生成成功 -> %s (%d KB)", path, os.path.getsize(path) // 1024)
    return path, "涩涩Qwen"


if __name__ == "__main__":
    # 自测：python se_color_handler.py <图片路径> "<指令>"
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else None
    q = sys.argv[2] if len(sys.argv) > 2 else "把连衣裙换成泳装"
    with open(p, "rb") as f:
        print(generate_image(q, f.read()))
