# -*- coding: utf-8 -*-
"""AI 对话模块：DeepSeek + 人设卡 + 短记忆 + 文本清洗

- chat(persona_id, user_text) -> 回复文本（同步，供 run_in_executor 调用）
- get_current_persona / set_current_persona：当前人设持久化到 admin_config.json
- 每个角色独立维护最近 HISTORY_MAX 轮对话记忆（进程内）
"""
import json
import os
import re
import threading
import urllib.request
from difflib import SequenceMatcher

from ai_personas import PERSONAS
from ai_secret import DEEPSEEK_API_KEY

ADMIN_CFG = "/opt/bilibot/admin/admin_config.json"
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
CONTEXT_MIN = 2
CONTEXT_MAX = 50
DEFAULT_CONTEXT = 10  # 默认保留最近对话轮数（user+assistant 各算一条）
BUDGET_MIN = 1
BUDGET_MAX = 5
DEFAULT_BUDGET = 2  # 每轮最多回复条数（像真人一样一次发 1~N 条）
QUEUE_MAX_MIN = 1
QUEUE_MAX_MAX = 10
DEFAULT_QUEUE_MAX = 3  # AI 请求最大排队条数（超出礼貌拒绝）

# 好感度
AFFECTION_FILE = "/opt/bilibot/ai_affection.json"
AFF_DEFAULT = 50
AFF_MIN = 0
AFF_MAX = 100

_affection = {}
_affection_lock = threading.Lock()

# 情绪分(1~7) -> 好感度增减
AFFECTION_DELTAS = {1: 3, 2: 2, 3: 1, 4: -2, 5: -4, 6: -6, 7: -10}

_history = {}
_history_lock = threading.Lock()
_conv_locks = {}


def _load_affection():
    global _affection
    try:
        with open(AFFECTION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _affection = data if isinstance(data, dict) else {}
    except Exception:
        _affection = {}


def _save_affection():
    tmp = AFFECTION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_affection, ensure_ascii=False, indent=2, fp=f)
    os.replace(tmp, AFFECTION_FILE)


def get_affection(persona_id, conv_key, user_id):
    """好感度：persona_id -> conv_key -> user_id -> 数值（默认 50）"""
    val = _affection.get(persona_id, {}).get(conv_key, {}).get(str(user_id))
    if val is None:
        return AFF_DEFAULT
    return max(AFF_MIN, min(AFF_MAX, int(val)))


def set_affection(persona_id, conv_key, user_id, value):
    value = max(AFF_MIN, min(AFF_MAX, int(value)))
    with _affection_lock:
        by_persona = _affection.setdefault(persona_id, {})
        by_conv = by_persona.setdefault(conv_key, {})
        by_conv[str(user_id)] = value
        _save_affection()


def reset_affection(persona_id, conv_key, user_id):
    with _affection_lock:
        by_persona = _affection.setdefault(persona_id, {})
        by_conv = by_persona.setdefault(conv_key, {})
        by_conv.pop(str(user_id), None)  # 移除即回到默认 50
        _save_affection()


def reset_affection_all(persona_id, conv_key):
    with _affection_lock:
        by_persona = _affection.setdefault(persona_id, {})
        by_persona.pop(conv_key, None)
        _save_affection()


def get_affection_rank(persona_id, conv_key):
    """返回 [(user_id, value), ...] 按好感度降序"""
    by_conv = _affection.get(persona_id, {}).get(conv_key, {})
    items = [(int(k), v) for k, v in by_conv.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def get_affection_all():
    """返回全部好感度数据（persona -> conv -> user -> value）的深拷贝"""
    with _affection_lock:
        return json.loads(json.dumps(_affection))


def _affection_prompt(value):
    """根据好感度生成语气指令"""
    if value < 20:
        return ("对方在你这里好感度很低（%d）。你对他冷淡疏远、惜字如金，语气拒人千里，"
                "通常只回半句话到一句话。" % value)
    if value < 40:
        return ("对方在你这里好感度偏低（%d）。你有些冷淡和保留，回复简短，不带热情。" % value)
    if value < 60:
        return ("对方在你这里好感度中等（%d）。你对他礼貌正常，"
                "像普通朋友一样自然交流。" % value)
    if value < 80:
        return ("对方在你这里好感度较高（%d）。你更热情友善、主动关心，语气亲近——"
                "但依然保持简短。" % value)
    return ("对方在你这里好感度很高（%d）。你非常亲近热情，会撒娇、表达喜爱——"
            "但依然保持简短。" % value)


def _classify_sentiment(user_text):
    """用 DeepSeek 快速给用户消息的情绪打分（1~7），失败默认 3（中性）"""
    system = (
        "你是一个对话情绪分析器，只输出一个整数（1~7），不要输出任何其他文字。"
        "根据用户这句话对对话角色的态度打分："
        "1=非常友善热情，2=友善礼貌，3=中性普通，4=冷淡敷衍，5=不耐烦或阴阳怪气，"
        "6=争吵指责，7=辱骂恶意。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
    try:
        text = _call_deepseek(messages, max_tokens=5, temperature=0)
        m = re.search(r"[1-7]", text)
        if m:
            return int(m.group(0))
    except Exception:
        pass
    return 3


def _apply_affection_delta(persona_id, conv_key, user_id, delta):
    """根据情绪分增减好感度（0 分时不再继续降）"""
    if delta == 0 or user_id in (None, "", "0"):
        return
    current = get_affection(persona_id, conv_key, user_id)
    if current <= 0 and delta < 0:
        return
    set_affection(persona_id, conv_key, user_id, current + delta)


_load_affection()


def list_personas():
    return list(PERSONAS.keys())


def get_voice_for_persona(persona_id):
    return PERSONAS[persona_id]["voice"]


def get_greeting(persona_id):
    return PERSONAS[persona_id].get("greeting", "")


def _load_admin():
    try:
        with open(ADMIN_CFG, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_admin(d):
    tmp = ADMIN_CFG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, ensure_ascii=False, indent=2, fp=f)
    os.replace(tmp, ADMIN_CFG)


def get_current_persona():
    pid = _load_admin().get("ai_persona")
    return pid if pid in PERSONAS else None


def set_current_persona(persona_id):
    d = _load_admin()
    d["ai_persona"] = persona_id if persona_id in PERSONAS else None
    _save_admin(d)


def get_context_length():
    """上下文长度（对话记忆轮数），管理面板可配置，持久化在 admin_config.json"""
    val = _load_admin().get("ai_context_length")
    if isinstance(val, int) and CONTEXT_MIN <= val <= CONTEXT_MAX:
        return val
    return DEFAULT_CONTEXT


def set_context_length(n):
    try:
        n = int(n)
    except Exception:
        n = DEFAULT_CONTEXT
    n = max(CONTEXT_MIN, min(CONTEXT_MAX, n))
    d = _load_admin()
    d["ai_context_length"] = n
    _save_admin(d)


def get_turn_budget():
    """每轮最多回复条数（AI 一次回应最多发几条消息），管理面板可配置"""
    val = _load_admin().get("ai_turn_budget")
    if isinstance(val, int) and BUDGET_MIN <= val <= BUDGET_MAX:
        return val
    return DEFAULT_BUDGET


def set_turn_budget(n):
    try:
        n = int(n)
    except Exception:
        n = DEFAULT_BUDGET
    n = max(BUDGET_MIN, min(BUDGET_MAX, n))
    d = _load_admin()
    d["ai_turn_budget"] = n
    _save_admin(d)


def get_voice_reply():
    """AI 回复方式：True=语音，False=文字；管理面板可配置"""
    val = _load_admin().get("ai_voice_reply")
    return val if isinstance(val, bool) else True


def set_voice_reply(flag):
    d = _load_admin()
    d["ai_voice_reply"] = bool(flag)
    _save_admin(d)


def get_queue_max():
    """AI 请求最大排队条数（多人同时询问时的队列上限）"""
    val = _load_admin().get("ai_queue_max")
    if isinstance(val, int) and QUEUE_MAX_MIN <= val <= QUEUE_MAX_MAX:
        return val
    return DEFAULT_QUEUE_MAX


def set_queue_max(n):
    try:
        n = int(n)
    except Exception:
        n = DEFAULT_QUEUE_MAX
    n = max(QUEUE_MAX_MIN, min(QUEUE_MAX_MAX, n))
    d = _load_admin()
    d["ai_queue_max"] = n
    _save_admin(d)


def reset_history(persona_id=None, conv_key=None):
    with _history_lock:
        if persona_id is not None and conv_key is not None:
            _history.pop((persona_id, conv_key), None)
        elif persona_id is not None:
            for key in list(_history.keys()):
                if key[0] == persona_id:
                    _history.pop(key, None)
        else:
            _history.clear()


def _call_deepseek(messages, max_tokens=180, temperature=0.8):
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + DEEPSEEK_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def chat_raw(messages, max_tokens=200, temperature=0.8):
    """底层 DeepSeek 调用（供其他模块复用）"""
    return _call_deepseek(messages, max_tokens=max_tokens, temperature=temperature)


def _sanitize(text, limit=150):
    """去掉 markdown 符号、emoji、多余空白；保留 ~ 等语气词"""
    text = re.sub(r"[*_#`>\[\]()]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\U0000FE0F]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _cut_sentence(text, limit):
    """在不超过 limit 的前提下，尽量按句末标点切断，避免句子中间被截断"""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    best = -1
    for marker in ("。", "！", "？", "～", "~", "…"):
        idx = cut.rfind(marker)
        if idx > best:
            best = idx
    if best >= int(limit * 0.4):  # 别切得太短
        return cut[:best + 1]
    return cut


def _has_question(text):
    """判断主回复是否包含问句（问号任意位置，或"吗/呢"等结尾式问句）"""
    t = text.strip()
    if "？" in t or "?" in t:
        return True
    if re.search(r"(吗|呢|怎么样|怎样|要不要|好不好|你觉得|想不想|是什么|为什么|去哪)$", t):
        return True
    return False


def _is_same(a, b):
    """判断两条文本是否重复（完全相同 / 包含 / 相似度过高）"""
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _follow_up(name, context_msgs):
    """让 AI 自己判断是否再补一句（延伸/反问）；不需要则返回 None"""
    system = (
        "你是%s。你刚刚回复了对方一句话。\n"
        "判断是否需要再补一句：\n"
        "- 如果上一条中已经包含问句（哪怕不在结尾，比如「要不要一起去？」或「你怎么看」），"
        "说明对话球已经抛回给对方，直接回复 STOP。\n"
        "- 如果上一条不是问句，且你确实还有一句值得说的（补充、打趣或一个新的小问题），"
        "写出一句全新的内容（15字以内，简短口语化，不用Markdown或表情符号）。\n"
        "- 绝对不能重复或复述上一条，绝对不能自问自答（问完问题又自己回答）。\n"
        "- 不想补充就只回复 STOP。" % name
    )
    messages = [{"role": "system", "content": system}] + context_msgs[-6:]
    try:
        text = _call_deepseek(messages, max_tokens=80, temperature=0.9)
    except Exception:
        return None
    text = text.strip()
    if (not text or text.upper().startswith("STOP")
            or text in ("……", "…", "。", "嗯", "啊")
            or "不用" in text or "不需要" in text or "结束" in text or "到此为止" in text):
        return None
    text = _cut_sentence(_sanitize(text), 40)
    return text or None


def chat(persona_id, user_text, conv_key="default", user_id="0"):
    """同步调用 DeepSeek，返回清洗后的消息列表（每轮 1~budget 条）"""
    # 同一会话（人设+渠道）的请求串行处理，避免上下文错乱
    key = (persona_id, conv_key)
    with _history_lock:
        lock = _conv_locks.setdefault(key, threading.Lock())
    with lock:
        persona = PERSONAS[persona_id]
        aff = get_affection(persona_id, conv_key, user_id)
        if aff <= 0:
            return []  # 好感度为 0：不回复
        ctx = get_context_length()
        budget = get_turn_budget()
        system = persona["system_prompt"] + (
            "\n【回复】务必简短：整段最多 2 句话、60 字以内，口语化；不要使用 Markdown 或表情符号；"
            "不要在问句之后立刻自己作答，把回答的机会留给对方。"
            "\n【好感度】" + _affection_prompt(aff)
        )
        with _history_lock:
            hist = _history.setdefault(key, [])
            hist.append({"role": "user", "content": user_text})
            history_msgs = hist[-ctx:]
        messages = [{"role": "system", "content": system}] + history_msgs
        main = _call_deepseek(messages, max_tokens=200)
        parts = [_cut_sentence(_sanitize(main), 80) or "……"]

        # 追加 AI 自判的续句（最多 budget-1 条）
        for _ in range(budget - 1):
            if len(parts) >= budget:
                break
            if _has_question(parts[-1]):
                break  # 主回复疑似问句：把球留给对方，不再续
            follow = _follow_up(persona_id, history_msgs + [
                {"role": "assistant", "content": parts[-1]},
            ])
            if follow is None:
                break
            if any(_is_same(follow, p) for p in parts):
                break  # 与已有内容重复，不再续
            parts.append(follow)

        with _history_lock:
            hist.append({"role": "assistant", "content": " ".join(parts)})
            if len(hist) > ctx * 2:
                del hist[: len(hist) - ctx * 2]

        # 内容好感度：根据用户这条消息的情绪增减好感度（回复基于增减前的数值生成）
        s = _classify_sentiment(user_text)
        _apply_affection_delta(persona_id, conv_key, user_id, AFFECTION_DELTAS.get(s, 0))
        return parts
