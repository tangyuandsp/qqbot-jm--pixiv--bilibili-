# -*- coding: utf-8 -*-
"""
语音功能：调用本地 GPT-SoVITS（经反向隧道）合成语音
支持 4 种音色：爱莉希雅 / 洛琪希 / 神里绫华 / 流萤

要点：
- 音色切换：调用本地 API 的 set_sovits_weights / set_gpt_weights（GET）
- 切换顺序：先 SoVITS（让 API 确定模型版本），再 GPT（按版本取 mute token）
- 同一时间只允许一个语音任务，避免本地显卡排队爆炸
"""
import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import config
from config import TTS_URL, VOICES, VOICE_SAY_DIR

logger = logging.getLogger("BiliBot")

# 音色别名（短名 → 正式名），方便输入
VOICE_ALIASES = {
    "爱莉": "爱莉希雅",
    "神里": "神里绫华",
    "洛琪": "洛琪希",
}

# 同一时间只允许一个语音任务（保护本地显卡/避免排队爆炸）
_voice_lock = asyncio.Lock()
_tts_timeout = 180
# 当前默认音色（/voice 切换后 /say 使用它；None = 跟随管理面板配置的默认音色）
_default_voice = {"name": None}
# 记录本地 API 当前已加载的音色，避免重复切换权重
_loaded_voice = {"name": None}


def resolve_voice(name: str):
    """把用户输入（含别名）归一化为正式音色名；未知返回 None"""
    if not name:
        return None
    name = name.strip()
    if name in VOICES:
        return name
    if name in VOICE_ALIASES and VOICE_ALIASES[name] in VOICES:
        return VOICE_ALIASES[name]
    return None


def get_current_voice() -> str:
    """当前默认音色（/voice 切换后 /say 使用它；未切换则跟随管理面板配置）"""
    return _default_voice["name"] or config.DEFAULT_VOICE


def _api_get(endpoint: str, params: dict) -> bytes:
    """调用本地 GPT-SoVITS 的 GET 接口（切换权重等）"""
    base = TTS_URL.rsplit("/", 1)[0]  # 去掉 /tts，得到 API 根地址
    url = f"{base}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _do_switch_weights(name: str) -> None:
    """同步执行音色切换：先 SoVITS 后 GPT"""
    voice = VOICES[name]
    logger.info(f"🎙️ 切换音色 → {name}")
    _api_get("set_sovits_weights", {"weights_path": voice["sovits_weights"]})
    _api_get("set_gpt_weights", {"weights_path": voice["gpt_weights"]})


def _request_tts(text: str, name: str) -> bytes:
    """同步请求本地 TTS，返回 wav 字节"""
    voice = VOICES[name]
    req = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": voice["ref_audio"],
        "prompt_text": voice["prompt_text"],
        "prompt_lang": voice["prompt_lang"],
        "speed_factor": voice["speed_factor"],
        "temperature": voice["temperature"],
        "text_split_method": voice.get("text_split_method", "cut5"),
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": False,
    }
    if voice.get("fragment_interval"):
        req["fragment_interval"] = voice["fragment_interval"]
    payload = json.dumps(req).encode("utf-8")
    req = urllib.request.Request(
        TTS_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_tts_timeout) as resp:
        data = resp.read()
    # 校验返回内容是不是合法 WAV：HTTP 200 但内容是错误 JSON / 空响应时，
    # 直接当失败处理，让上层走文字保底，避免发出去一个坏音频
    if not data or not data.startswith(b"RIFF"):
        snippet = data[:80].decode("utf-8", errors="replace")
        raise ValueError(f"TTS 返回内容不是有效音频: {snippet}")
    if len(data) < 128:
        raise ValueError("TTS 返回音频过短")
    return data


def _ensure_loaded(name: str) -> None:
    """确保本地 API 已加载指定音色权重（已加载则跳过）"""
    if _loaded_voice["name"] != name:
        _do_switch_weights(name)
        _loaded_voice["name"] = name


async def switch_voice(name: str) -> None:
    """管理员主动切换默认音色（/voice <名称>）——总是重新加载，确保生效"""
    async with _voice_lock:
        _default_voice["name"] = name
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, _do_switch_weights, name)
        except Exception:
            _loaded_voice["name"] = None
            raise
        _loaded_voice["name"] = name


def set_default_voice(name: str) -> None:
    """设置默认音色（不加载权重），供每日自动轮换使用；手动切换请用 switch_voice"""
    if name in VOICES:
        _default_voice["name"] = name


async def generate_voice(text: str, voice_name: str = None) -> str:
    """生成 wav 文件并返回路径；失败抛异常。voice_name 为空则用当前默认音色"""
    name = resolve_voice(voice_name) or get_current_voice()
    async with _voice_lock:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, _ensure_loaded, name)
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, _request_tts, text, name)
        except Exception:
            # 本地服务重启/隧道断开后缓存可能失效，清空以便下次强制重新加载
            _loaded_voice["name"] = None
            raise
        os.makedirs(VOICE_SAY_DIR, exist_ok=True)
        _cleanup_old()
        path = os.path.join(
            VOICE_SAY_DIR,
            f"say_{int(time.time() * 1000)}_{VOICES[name]['id']}.wav",
        )
        with open(path, "wb") as f:
            f.write(data)
        logger.info(f"🎙️ 语音已生成[{name}]: {path} ({len(data) / 1024:.0f} KB)")
        return path


def _cleanup_old():
    """删除 1 小时前的旧语音文件，防止磁盘堆积"""
    cutoff = time.time() - 3600
    try:
        for name in os.listdir(VOICE_SAY_DIR):
            p = os.path.join(VOICE_SAY_DIR, name)
            try:
                if name.startswith("say_") and os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
