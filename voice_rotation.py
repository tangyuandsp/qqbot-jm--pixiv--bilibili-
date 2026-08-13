# -*- coding: utf-8 -*-
"""音色自动轮换

- 定时宽慰（早晨/傍晚/睡前三次）按 VOICE_NAMES 顺序轮播：
  早晨=第1个音色，傍晚=第2个，睡前=第3个，跨天继续。
- 日常聊天默认音色：每天自动换下一个（一天一换）。
- 手动 /voice 切换只改变当前生效音色，不影响轮换指针，
  下一次自动轮换仍按「更改前的顺序」继续。

轮换指针持久化在 voice_rotation.json。
"""
import datetime
import json
import os
import threading

import config

ROTATION_FILE = "/opt/bilibot/voice_rotation.json"
_lock = threading.Lock()


def _load():
    try:
        with open(ROTATION_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _save(d):
    tmp = ROTATION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, ensure_ascii=False, indent=2, fp=f)
    os.replace(tmp, ROTATION_FILE)


def _order():
    return list(config.VOICE_NAMES)


def next_greeting_voice():
    """返回下一个定时宽慰音色并推进轮换指针"""
    with _lock:
        d = _load()
        idx = int(d.get("greeting_index", 0))
        names = _order()
        voice = names[idx % len(names)]
        d["greeting_index"] = idx + 1
        _save(d)
    return voice


def maybe_rotate_daily():
    """若今天还没轮换过日常默认音色，则取下一个并返回；已轮换返回 None"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with _lock:
        d = _load()
        if d.get("daily_date") == today:
            return None
        idx = int(d.get("daily_index", 0))
        names = _order()
        voice = names[idx % len(names)]
        d["daily_index"] = idx + 1
        d["daily_date"] = today
        _save(d)
    return voice


def get_state():
    return _load()
