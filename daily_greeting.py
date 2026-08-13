# -*- coding: utf-8 -*-
"""定时情感陪伴语音

三个时段：
  morning  09:00  晨间鼓励
  evening  18:30  下班宽慰
  night    23:30  睡前安抚

提示词精心设计：结合当天日期 / 星期 / 季节 / 星座意象，像老友漫不经心的宽慰，
轻轻提到花草鱼虫、晨光晚风等生活意象，绝不千篇一律。

配置存于 admin_config.json 的 "daily_greeting" 段，支持：
  总开关 / 目标（私聊 QQ 或群号）/ 每个时段上次发送日期（防重复）
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

import ai_handler

SLOTS = {
    "morning": (9, 0, "晨间鼓励"),
    "evening": (18, 30, "下班宽慰"),
    "night": (23, 30, "睡前安抚"),
}

MAX_TEXT = 140  # 语音独白长度上限（约 2~4 句话，避免语音过长）
HISTORY_LIMIT = 7  # 每个时段记住最近 N 天文案，用于防重复

# 二十四节气（近似公历日期）
SOLAR_TERMS = [
    (1, 6, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"),
    (3, 6, "惊蛰"), (3, 21, "春分"), (4, 5, "清明"), (4, 20, "谷雨"),
    (5, 6, "立夏"), (5, 21, "小满"), (6, 6, "芒种"), (6, 21, "夏至"),
    (7, 7, "小暑"), (7, 23, "大暑"), (8, 7, "立秋"), (8, 23, "处暑"),
    (9, 8, "白露"), (9, 23, "秋分"), (10, 8, "寒露"), (10, 23, "霜降"),
    (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 22, "冬至"),
]

NEW_MOON_REF = datetime.datetime(2000, 1, 6, 18, 14)
SYNODIC_MONTH = 29.530588853


def _load_cfg():
    d = ai_handler._load_admin()
    cfg = d.setdefault("daily_greeting", {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("targets", [])
    cfg.setdefault("last_sent", {})
    return d, cfg


def _save_cfg(d):
    ai_handler._save_admin(d)


def get_enabled():
    _, cfg = _load_cfg()
    return bool(cfg.get("enabled"))


def _recent_texts(slot):
    _, cfg = _load_cfg()
    return list(cfg.setdefault("history", {}).get(slot, []))


def record_history(slot, text):
    """记录当天已发送的文案（防重复记忆）"""
    d, cfg = _load_cfg()
    hist = cfg.setdefault("history", {}).setdefault(slot, [])
    hist.append(text)
    if len(hist) > HISTORY_LIMIT:
        del hist[:len(hist) - HISTORY_LIMIT]
    _save_cfg(d)


def set_enabled(flag):
    d, cfg = _load_cfg()
    cfg["enabled"] = bool(flag)
    _save_cfg(d)


def get_targets():
    _, cfg = _load_cfg()
    return list(cfg.get("targets", []))


def was_sent_today(slot):
    _, cfg = _load_cfg()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return cfg["last_sent"].get(slot) == today


def mark_sent(slot):
    d, cfg = _load_cfg()
    cfg["last_sent"][slot] = datetime.datetime.now().strftime("%Y-%m-%d")
    _save_cfg(d)


def add_target(ttype, tid):
    d, cfg = _load_cfg()
    targets = cfg["targets"]
    if not any(t["type"] == ttype and t["id"] == tid for t in targets):
        targets.append({"type": ttype, "id": int(tid)})
        _save_cfg(d)
        return True
    return False


def remove_target(ttype, tid):
    d, cfg = _load_cfg()
    before = len(cfg["targets"])
    cfg["targets"] = [t for t in cfg["targets"] if not (t["type"] == ttype and t["id"] == int(tid))]
    if len(cfg["targets"]) != before:
        _save_cfg(d)
        return True
    return False


def _zodiac(month, day):
    signs = [
        ("摩羯座", 1, 19), ("水瓶座", 2, 18), ("双鱼座", 3, 20), ("白羊座", 4, 19),
        ("金牛座", 5, 20), ("双子座", 6, 21), ("巨蟹座", 7, 22), ("狮子座", 8, 22),
        ("处女座", 9, 22), ("天秤座", 10, 23), ("天蝎座", 11, 22), ("射手座", 12, 21),
    ]
    for name, m, d in signs:
        if (month, day) <= (m, d):
            return name
    return "摩羯座"


def _season(month):
    if month in (3, 4, 5):
        return "春意正浓"
    if month in (6, 7, 8):
        return "盛夏时节"
    if month in (9, 10, 11):
        return "秋意渐起"
    return "冬日静谧"


def _solar_term(month, day):
    """当前所处的节气（近似）"""
    cur = (month, day)
    prev = None
    nxt = None
    for m, d, name in SOLAR_TERMS:
        if (m, d) <= cur:
            prev = (m, d, name)
        else:
            nxt = (m, d, name)
            break
    if prev is None:
        prev = SOLAR_TERMS[-1]
    if nxt is None:
        nxt = SOLAR_TERMS[0]
    if cur == prev[:2]:
        return "正值" + prev[2]
    return prev[2] + "已过，" + nxt[2] + "将至"


def _moon_phase(day):
    """月相（按朔望月近似）"""
    days = (day - NEW_MOON_REF).total_seconds() / 86400.0
    frac = (days % SYNODIC_MONTH) / SYNODIC_MONTH
    if frac < 0.03 or frac >= 0.97:
        return "新月"
    if frac < 0.22:
        return "娥眉月"
    if frac < 0.28:
        return "上弦月"
    if frac < 0.47:
        return "盈凸月"
    if frac < 0.53:
        return "满月"
    if frac < 0.72:
        return "亏凸月"
    if frac < 0.78:
        return "下弦月"
    return "残月"


def _get_weather(city):
    """抓当天天气（wttr.in 免费接口），失败返回 None"""
    if not city:
        return None
    try:
        url = "https://wttr.in/%s?format=%%C+%%t+%%w&lang=zh" % urllib.parse.quote(city)
        with urllib.request.urlopen(url, timeout=8) as r:
            text = r.read().decode("utf-8", "replace").strip()
        return text if text else None
    except Exception:
        return None


def get_weather_city():
    _, cfg = _load_cfg()
    return cfg.get("weather_city", "") or ""


def set_weather_city(city):
    d, cfg = _load_cfg()
    cfg["weather_city"] = (city or "").strip()
    _save_cfg(d)


SLOT_INSTRUCTIONS = {
    "morning": (
        "【场景：晨间鼓励】像老友在清晨的露水边轻轻拍了拍你的肩，为崭新的一天注入温柔的希望。"
        "语气温暖、有元气，但绝不打鸡血、不喊口号。"
    ),
    "evening": (
        "【场景：下班宽慰】像老友在暮色里陪你慢慢走回家，宽慰一天的疲惫。"
        "语气柔和、放松、有陪伴感，承认今天的辛苦，但不必渲染沉重。"
    ),
    "night": (
        "【场景：睡前安抚】像老友在深夜窗前轻声细语，让你安心放下白天的纷扰。"
        "语气平静、温暖、像羽毛一样轻，最后自然地道一声晚安。"
    ),
}


def _build_system_prompt(slot, persona_id):
    now = datetime.datetime.now()
    weekdays = "一二三四五六日"
    season = _season(now.month)
    solar_term = _solar_term(now.month, now.day)
    moon_phase = _moon_phase(now)

    # 意象：节气 + 月相（星座已移除，避免每天重复提到某星座）
    weather = _get_weather(get_weather_city())
    anchor_line = "节气·" + solar_term + "；月相·" + moon_phase
    if weather:
        anchor_line += "；今日天气·" + weather

    recent = _recent_texts(slot)
    avoid = ""
    if recent:
        avoid = (
            "\n【务必避开的内容】你最近几天已经说过这些话，今天的回复绝对不要重复它们的"
            "意象、句式、开头和情绪走向：\n"
            + "\n".join("- " + t for t in recent)
            + "\n"
        )
    return (
        "你是%s，一个温柔而细腻的说话者。请给一位熟识的朋友写一段简短而美好的语音独白。\n"
        "今天是%d月%d日 星期%s，%s。\n"
        "【今日意象】%s\n"
        "【要求】\n"
        "1. %s\n"
        "2. 结合今天的日期、季节和【今日意象】（只从中选取一个轻轻融入即可，"
        "不要堆砌所有意象，更不要每天都提同一类）；绝对不要提到任何星座"
        "（比如狮子座、处女座等），也不要暗示星座——让这段话独一无二，绝不千篇一律；"
        "不要重复昨天说过的话，更不要用套话。\n"
        "3. 像老友漫不经心的宽慰：别把关心喊出来，而是藏在具体的小事里——"
        "可以轻轻提到花草鱼虫、晨光晚风、茶香、星月、街角旧店、窗台绿植等生活意象，"
        "再自然地把话题收回到对方身上。\n"
        "4. 语言温柔、口语化、有画面感，像真的在对一个熟悉的人说话；句子之间留一点呼吸感。\n"
        "5. 整段控制在 2~4 句话、120 字以内。不要使用 Markdown、表情符号，不要写成作文或鸡汤。\n"
        "6. 今天是%s，一年有 365 天，你有无数种不同的说法——务必让它只属于今天。"
        "%s"
        % (persona_id, now.month, now.day, weekdays[now.weekday()], season, anchor_line,
           SLOT_INSTRUCTIONS[slot], now.strftime("%Y年%m月%d日"), avoid)
    )


def generate_message(slot, persona_id):
    """生成一段语音独白文本（失败返回 None）"""
    system = _build_system_prompt(slot, persona_id)
    try:
        text = ai_handler.chat_raw(
            [{"role": "system", "content": system}],
            max_tokens=300,
            temperature=0.9,
        )
    except Exception:
        return None
    text = ai_handler._sanitize(text)
    if not text:
        return None
    return text[:MAX_TEXT]
