#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时提醒：DeepSeek 意图解析 + 要素追问 + 到点前 5 分钟提醒

触发：群聊 @机器人 / 白名单私聊，消息含提醒关键词（或处于补全对话中）。
流程：解析「时间+事项」→ 缺要素则按当前人设俏皮追问（存草稿，跨消息补全）
      → 要素齐全后创建任务（持久化 reminders.json）
      → 到点前 5 分钟 + 到点各提醒一次（群聊 @ 发起人）。
"""
import datetime
import json
import logging
import os
import re
import threading
import uuid

import ai_handler
from ai_personas import PERSONAS

logger = logging.getLogger("Reminder")

REMINDS_FILE = "/opt/bilibot/reminders.json"
PENDING_TTL = datetime.timedelta(minutes=5)  # 提醒草稿超时：5 分钟没补全自动放弃，恢复正常聊天
LEAD_MINUTES = 5   # 提前 5 分钟提醒
EARLY_MINUTES = 30  # 提前 30 分钟提醒

# 到点后未确认的“俏皮轰炸”参数
BOMB_INTERVAL_SEC = 60     # 每隔 60 秒催一次
BOMB_MAX_COUNT = 10        # 最多催 10 次
BOMB_MAX_MINUTES = 30      # 超过 30 分钟自动放弃

# 提醒触发关键词（预判用；真正判定交给 DeepSeek）
_HINT_KEYWORDS = ("提醒", "别忘了", "别忘", "定时", "到点", "喊我", "叫我", "催我")

# 纯确认词（群聊/私聊回应提醒）：命中则俏皮收尾并消费消息
_ACK_RE = re.compile(
    r"^(好的?|好哒|好嘞|好滴|嗯|嗯嗯|嗯呢|嗯嗯嗯|ok|okk|okay|收到|收到啦|知道了|知道啦|"
    r"晓得|晓得了|行|行吧|没问题|可以|👌)[!！~～。.、\s]*$"
)

_lock = threading.Lock()
_ws = {"ws": None}
_sender = {"fn": None}  # 由 main.py 注入 async fn(ws, task, text) -> message_id


# ────────────────────────── 持久化 ──────────────────────────

def _load() -> dict:
    try:
        with open(REMINDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "tasks" in data:
            return data
    except Exception:
        pass
    return {"tasks": [], "pending": {}}


def _save(data: dict) -> None:
    tmp = REMINDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REMINDS_FILE)


def _pending_key(channel: str, target_id, user_id) -> str:
    return f"{channel}:{target_id}:{user_id}"


def get_pending(channel: str, target_id, user_id) -> dict | None:
    with _lock:
        data = _load()
        p = data.get("pending", {}).get(_pending_key(channel, target_id, user_id))
        if not p:
            return None
        # 超时清掉
        try:
            created = datetime.datetime.fromisoformat(p.get("created_at", ""))
        except Exception:
            created = datetime.datetime.now()
        if datetime.datetime.now() - created > PENDING_TTL:
            data["pending"].pop(_pending_key(channel, target_id, user_id), None)
            _save(data)
            return None
        return dict(p)


def save_pending(channel: str, target_id, user_id, p: dict) -> None:
    with _lock:
        data = _load()
        data["pending"][_pending_key(channel, target_id, user_id)] = p
        _save(data)


def clear_pending(channel: str, target_id, user_id) -> None:
    with _lock:
        data = _load()
        data["pending"].pop(_pending_key(channel, target_id, user_id), None)
        _save(data)


def add_task(task: dict) -> None:
    with _lock:
        data = _load()
        data["tasks"].append(task)
        _save(data)


def load_tasks() -> list:
    with _lock:
        return _load().get("tasks", [])


def save_tasks(tasks: list) -> None:
    with _lock:
        data = _load()
        data["tasks"] = tasks
        _save(data)


# ────────────────────────── DeepSeek 解析 ──────────────────────────

def _parse(text: str, now: datetime.datetime, existing: dict | None = None) -> dict | None:
    """解析用户消息，返回 {is_reminder, time, event, missing, ask}；失败返回 None"""
    existing = existing or {}
    has_existing = bool(existing.get("time") or existing.get("event"))
    week = ("一", "二", "三", "四", "五", "六", "日")[now.weekday()]
    sys_lines = [
        "你是定时提醒解析助手。",
        f"当前时间：{now.strftime('%Y-%m-%d %H:%M')}（星期{week}）。",
        "用户想设置一个提醒。把相对时间（明天上午9点、半小时后、今晚8点、后天下午等）",
        "换算成绝对时间，格式 YYYY-MM-DD HH:MM（24小时制）。",
        "用户只说大概时段时，按：清晨=07:00、上午=09:00、中午=12:00、下午=14:00、傍晚=17:30、晚上=20:00、深夜=23:00 处理。",
    ]
    if has_existing:
        sys_lines.append(
            f"用户在补充一条未完成的提醒：已有时间={existing.get('time') or '未知'}，"
            f"已有事项={existing.get('event') or '未知'}。请结合已有信息，从用户最新回复中提取缺失的要素，视为提醒请求。"
        )
    sys_lines.append(
        "只输出一个 JSON 对象，不要任何其他文字或解释：\n"
        '{"is_reminder": true或false, "time": "YYYY-MM-DD HH:MM"或null, '
        '"time_text": "用户原话里的时间描述（如 明天上午9点）"或null, '
        '"event": "具体事项（如 开会、赶火车、吃药）"或null, '
        '"missing": ["time"]或["event"]或[], "ask": "追问文本或空字符串"}'
    )
    sys_lines.append(
        "说明：is_reminder=这句话是否在请求设置提醒；time/time_text=能确定的时间，缺则null；"
        "event=用户明确说的具体事项，**如果用户没说具体要提醒做什么事（例如只说'提醒我'），event 必须为 null**，"
        "绝不要用'提醒事项''事情'这类占位词。"
        "missing=还缺哪些要素（齐全则[]）；ask=若缺要素，用自然俏皮、像真人聊天的口吻问一句缺失的信息"
        "（绝不要说'请提供时间/事项'这种机械话术），齐全则为空字符串。"
    )
    try:
        raw = ai_handler.chat_raw(
            [{"role": "system", "content": "\n".join(sys_lines)},
             {"role": "user", "content": text.strip()}],
            max_tokens=300, temperature=0.2,
        )
        m = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(m.group(0)) if m else json.loads(raw)
        if not isinstance(data, dict):
            return None
        if has_existing:
            data.setdefault("is_reminder", True)
        return data
    except Exception as exc:
        logger.error(f"提醒解析失败: {exc}")
        return None


def _default_ask(p: dict) -> str:
    if not p.get("time"):
        return "诶，那你打算什么时候呀？给我个时间我好掐点喊你~"
    return "那……你要我提醒你做什么呢？"


# ────────────────────────── 文案生成（人设联动） ──────────────────────────

def _gen_line(system: str) -> str | None:
    try:
        text = ai_handler.chat_raw(
            [{"role": "system", "content": system},
             {"role": "user", "content": "（请直接回复）"}],
            max_tokens=120, temperature=0.8,
        )
        text = (text or "").strip()
        return text or None
    except Exception:
        return None


def build_confirm(persona: str, p: dict, time_text: str) -> str:
    """创建成功后的俏皮确认文案"""
    event = p.get("event", "")
    time_s = p.get("time", "")
    line = _gen_line(
        f"你是{persona}，说话俏皮自然、像真人，1~2句，不用Markdown。"
        f"用户让你在「{time_text}」提醒TA「{event}」，现在提醒已设定成功。请用{persona}的口吻回一句确认（要带上时间点和事项，语气轻松可爱）。"
    )
    if line:
        return line
    return f"好嘞~ {time_s} 我会记得提醒你「{event}」的，安心~"


def _clock_text(dt: datetime.datetime) -> str:
    """把时刻转成自然说法：上午10点 / 下午3点30"""
    h, m = dt.hour, dt.minute
    if 5 <= h < 12:
        part = "上午"
    elif 12 <= h < 14:
        part = "中午"
    elif 14 <= h < 18:
        part = "下午"
    elif 18 <= h < 23:
        part = "晚上"
    else:
        part = "凌晨"
    hh = h % 12 or 12
    return f"{part}{hh}点" + (f"{m:02d}" if m else "")


def _relative_time_text(due: datetime.datetime, now: datetime.datetime) -> str:
    """把到期时间换算成相对当前的自然说法：今天/明天/昨天/X月X日 + 时段"""
    today = now.date()
    due_date = due.date()
    clock = _clock_text(due)
    if due_date == today:
        return f"今天{clock}"
    if due_date == today + datetime.timedelta(days=1):
        return f"明天{clock}"
    if due_date == today - datetime.timedelta(days=1):
        return f"昨天{clock}"
    return f"{due.month}月{due.day}日{clock}"


def build_notice(persona: str, event: str, due_text: str, stage: str) -> str:
    """到点前 5 分钟（pre）/ 到点（due）的提醒文案"""
    if stage == "early":
        line = _gen_line(
            f"你是{persona}，俏皮自然、像真人，1~2句，不用Markdown。"
            f"用户设定的提醒「{event}」还有半小时（{due_text}）就到了。请用{persona}的口吻提前知会一句，轻松可爱。"
            f"提醒里要自然带上时间描述「{due_text}」（例如：今天下午3点就快到啦，半小时后要去「{event}」哦）。"
        )
        if line:
            return line
        return f"⏰ 还有半小时（{due_text}）就要「{event}」啦，先记在心里哦~"
    if stage == "pre":
        line = _gen_line(
            f"你是{persona}，俏皮自然、像真人，1~2句，不用Markdown。"
            f"用户设定的提醒「{event}」还有5分钟（{due_text}）就到了。请用{persona}的口吻催一句，轻松可爱。"
            f"提醒里要自然带上时间描述「{due_text}」（例如：今天上午9点55啦，5分钟后要「{event}」哦）。"
        )
        if line:
            return line
        return f"⏰ 还有5分钟（{due_text}）就要「{event}」啦，准备一下~"
    line = _gen_line(
        f"你是{persona}，俏皮自然、像真人，1~2句，不用Markdown。"
        f"用户设定的提醒「{event}」到点了（{due_text}）。请用{persona}的口吻提醒TA现在该去做了。"
        f"提醒里要自然带上时间描述「{due_text}」（例如：今天下午3点啦，该去「{event}」咯）。"
    )
    if line:
        return line
    return f"⏰ 到点啦（{due_text}）！该去「{event}」了！"


_BOMB_TEMPLATES = [
    "喂喂~ 刚刚说的「{event}」别忘了哦，我可都记着呢",
    "哼哼，装没看到是吧？{due_text}的「{event}」它还在等你呢",
    "……你是不是把我屏蔽了？那我再喊一声：{event}！",
    "好啦不逗你了，但这个真的要紧，看到了回我一声嘛",
]


def build_bomb(persona: str, event: str, due_text: str, count: int) -> str:
    """到点后用户没回应的俏皮轰炸文案（次数越多越缠人）"""
    line = _gen_line(
        f"你是{persona}，俏皮自然、像真人，1~2句，不用Markdown。"
        f"你提醒过用户「{event}」（{due_text}），但用户一直没回应，这已经是第{count + 1}次催了。"
        f"请用{persona}的口吻越来越俏皮地再催一次，可以假装委屈、撒娇、或耍赖，但别真生气，可爱一点。"
    )
    if line:
        return line
    idx = min(count, len(_BOMB_TEMPLATES) - 1)
    return _BOMB_TEMPLATES[idx].format(event=event, due_text=due_text)


def build_ack(persona: str, event: str) -> str:
    """用户终于回应的俏皮收尾"""
    line = _gen_line(
        f"你是{persona}，俏皮自然、像真人，1句，不用Markdown。"
        f"用户终于回应了你催的「{event}」，请用{persona}的口吻轻松地确认收到，语气俏皮（比如：收到收到~ 这就放过你、好耶、这还差不多）。"
    )
    if line:
        return line
    return "收到收到！这就放过你~"


# ────────────────────────── 意图识别 / 处理入口 ──────────────────────────

def contains_hint(text: str) -> bool:
    """关键词预判：命中才进入 DeepSeek 解析（避免所有消息都调 AI）"""
    return any(k in text for k in _HINT_KEYWORDS)


async def handle_text(ws, text: str, channel: str, target_id, user_id, reply_fn) -> bool:
    """处理一条消息：返回 True=已消费（提醒流程），False=不是提醒，交给原逻辑。

    channel: 'group' | 'private'; target_id: 群号或 QQ; reply_fn(text)->发送回复
    """
    now = datetime.datetime.now()
    pending = get_pending(channel, target_id, user_id)

    # 有草稿：任何消息都视为补充信息（跳过关键词预判）
    if not pending and not contains_hint(text):
        return False

    p = pending or {"time": None, "event": None, "created_at": now.isoformat()}
    parsed = _parse(text, now, existing=pending)
    if parsed is None:
        # 解析失败：有草稿就留草稿问一句，否则放弃
        if pending:
            await reply_fn(_default_ask(p))
            return True
        return False
    if not parsed.get("is_reminder"):
        if pending:
            await reply_fn(_default_ask(p))
            return True
        return False

    # 合并已确认要素
    if parsed.get("time"):
        p["time"] = parsed["time"]
    if parsed.get("time_text"):
        p["time_text"] = parsed["time_text"]
    if parsed.get("event"):
        p["event"] = parsed["event"]
    missing = parsed.get("missing") or []
    if (not p.get("time") or not p.get("event")) and missing:
        p["created_at"] = now.isoformat()
        save_pending(channel, target_id, user_id, p)
        ask = parsed.get("ask") or _default_ask(p)
        await reply_fn(ask)
        return True
    if not p.get("time") or not p.get("event"):
        # 模型没给 missing，但确实缺要素 → 兜底追问
        p["created_at"] = now.isoformat()
        save_pending(channel, target_id, user_id, p)
        await reply_fn(_default_ask(p))
        return True

    # 要素齐全 → 创建任务
    clear_pending(channel, target_id, user_id)
    try:
        due = datetime.datetime.strptime(p["time"], "%Y-%m-%d %H:%M")
    except Exception:
        due = now + datetime.timedelta(minutes=5)
        p["time"] = due.strftime("%Y-%m-%d %H:%M")
    notify_at = due - datetime.timedelta(minutes=LEAD_MINUTES)
    early_at = due - datetime.timedelta(minutes=EARLY_MINUTES)
    persona = ai_handler.get_current_persona() or "爱莉希雅"
    task = {
        "id": uuid.uuid4().hex[:12],
        "channel": channel,
        "target_id": target_id,
        "user_id": user_id,
        "event": p["event"],
        "due_at": due.strftime("%Y-%m-%d %H:%M"),
        "notify_at": notify_at.strftime("%Y-%m-%d %H:%M"),
        "early_at": early_at.strftime("%Y-%m-%d %H:%M"),
        "time_text": p.get("time_text") or p["time"],
        "notice_channel": "private",  # 提醒本体（提前30分钟/5分钟/到点/轰炸）一律私聊发送
        "persona": persona,
        "early_sent": False,
        "pre_sent": False,
        "due_sent": False,
        "confirmed": False,
        "bomb_count": 0,
        "last_bomb_at": None,
        "remind_msg_id": None,
        "created_at": now.isoformat(),
    }
    add_task(task)
    confirm = build_confirm(persona, p, p.get("time_text") or p["time"])
    if channel == "group":
        confirm += "\n（到点我会私聊提醒你哦，记得通过我的好友申请～）"
    await reply_fn(confirm)
    logger.info(f"⏰ 已创建提醒: {channel}/{target_id} {p['event']} @ {p['time']}")
    return True


async def try_confirm_group(ws, event: dict, reply_fn) -> str:
    """群聊确认：用户回复提醒消息或@机器人 = 已确认。

    返回 'consumed'（纯确认词，已俏皮收尾，消息消费掉）/ 'confirmed'（已确认但消息还要继续处理）/ ''（无待确认提醒）
    """
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    raw_message = event.get("raw_message", "")
    if not user_id or not raw_message:
        return ""
    # 是否回复了某条消息（CQ:reply）
    reply_id = None
    m = re.search(r"\[CQ:reply,id=(\d+)\]", raw_message)
    if m:
        reply_id = int(m.group(1))
    # 是否 @机器人
    self_id = str(event.get("self_id", ""))
    at_me = False
    for seg in event.get("message", []):
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == self_id or qq == "all":
                at_me = True
    tasks = load_tasks()
    hit = None
    for t in tasks:
        if (t.get("channel") == "group" and t.get("target_id") == group_id
                and t.get("user_id") == user_id
                and t.get("due_sent") and not t.get("confirmed")):
            # 回复了提醒消息 或 @机器人，二者其一即确认
            if (reply_id and reply_id == t.get("remind_msg_id")) or at_me:
                hit = t
                break
    if hit is None:
        return ""
    hit["confirmed"] = True
    save_tasks(tasks)
    clean = re.sub(r"\[CQ:[^\]]*\]", "", raw_message).strip()
    if _is_ack(clean):
        persona = hit.get("persona") or ai_handler.get_current_persona() or "爱莉希雅"
        await reply_fn(build_ack(persona, hit.get("event", "")))
        return "consumed"
    return "confirmed"


async def try_confirm_private(ws, event: dict, reply_fn) -> str:
    """私聊确认：用户发任意消息 = 已确认（一对一，无需 @/回复）"""
    user_id = event.get("user_id")
    raw_message = event.get("raw_message", "")
    if not user_id or not raw_message:
        return ""
    tasks = load_tasks()
    hit = None
    for t in tasks:
        # 私聊创建，或群聊创建但提醒私发 → 都算私聊可确认
        private_notice = t.get("notice_channel") == "private" or t.get("channel") == "private"
        if (private_notice and t.get("user_id") == user_id
                and t.get("due_sent") and not t.get("confirmed")):
            hit = t
            break
    if hit is None:
        return ""
    hit["confirmed"] = True
    save_tasks(tasks)
    clean = re.sub(r"\[CQ:[^\]]*\]", "", raw_message).strip()
    if _is_ack(clean):
        persona = hit.get("persona") or ai_handler.get_current_persona() or "爱莉希雅"
        await reply_fn(build_ack(persona, hit.get("event", "")))
        return "consumed"
    return "confirmed"


async def handle_command(ws, text: str, channel: str, target_id, user_id, reply_fn) -> bool:
    """/remind list | del <id> | clear —— 返回 True=已处理"""
    args = text.strip().split()
    if not args or args[0].lower() != "/remind":
        return False
    if len(args) == 1 or args[1].lower() in ("list", "ls"):
        tasks = [t for t in load_tasks()
                 if t.get("channel") == channel and t.get("target_id") == target_id]
        if not tasks:
            await reply_fn("⏰ 当前还没有进行中的提醒~")
            return True
        lines = ["⏰ 进行中的提醒："]
        for t in tasks:
            done = "✔" if t.get("due_sent") else ("⏳" if t.get("pre_sent") else "⏱")
            lines.append(f"  {done} {t['id']} {t['time_text']} 「{t['event']}」")
        await reply_fn("\n".join(lines))
        return True
    if args[1].lower() in ("del", "delete", "cancel") and len(args) >= 3:
        tid = args[2]
        tasks = load_tasks()
        hit = [t for t in tasks if t["id"] == tid and t.get("channel") == channel and t.get("target_id") == target_id]
        if not hit:
            await reply_fn("❓ 没找到这个提醒~")
            return True
        if hit[0].get("user_id") != user_id and user_id not in _admin_qq():
            await reply_fn("⛔ 只有发起人/管理员可以删除~")
            return True
        save_tasks([t for t in tasks if t["id"] != tid])
        await reply_fn(f"✅ 已取消提醒「{hit[0]['event']}」~")
        return True
    if args[1].lower() == "clear":
        tasks = load_tasks()
        save_tasks([t for t in tasks
                    if not (t.get("channel") == channel and t.get("target_id") == target_id)])
        clear_pending(channel, target_id, user_id)
        await reply_fn("🧹 已清空当前会话的提醒~")
        return True
    await reply_fn("用法：/remind list | /remind del <id> | /remind clear")
    return True


def _admin_qq() -> list:
    try:
        import config
        return list(config.VOICE_CONTROL_USERS)
    except Exception:
        return []


# ────────────────────────── 定时检查循环 ──────────────────────────

async def reminder_loop():
    import asyncio
    while True:
        try:
            await _tick()
        except Exception as exc:
            logger.error(f"⏰ 提醒循环出错: {exc}")
        await asyncio.sleep(30)


async def _tick():
    ws = _ws.get("ws")
    if ws is None:
        return
    now = datetime.datetime.now()
    tasks = load_tasks()
    changed = False
    for t in tasks:
        due_s = t.get("due_at", "")
        notify_s = t.get("notify_at", "")
        due = datetime.datetime.strptime(due_s, "%Y-%m-%d %H:%M") if due_s else None
        notify = datetime.datetime.strptime(notify_s, "%Y-%m-%d %H:%M") if notify_s else None
        persona = t.get("persona") or ai_handler.get_current_persona() or "爱莉希雅"
        event = t.get("event", "")
        if due is None:
            continue
        # 到点提醒按“当前时间”动态换算相对说法（创建时存的 time_text 跨天后会过期）
        due_text = _relative_time_text(due, now)
        # 提前 30 分钟
        early_s = t.get("early_at", "")
        early = datetime.datetime.strptime(early_s, "%Y-%m-%d %H:%M") if early_s else None
        if early is not None and not t.get("early_sent") and now >= early:
            text = build_notice(persona, event, due_text, "early")
            mid = await _send(ws, t, text)
            t["early_sent"] = True
            if mid and t.get("channel") == "group":
                t["remind_msg_id"] = mid
            changed = True
            logger.info(f"⏰ 提前30分钟提醒: {event} @ {due_text}")
        # 提前 5 分钟
        if notify is not None and not t.get("pre_sent") and now >= notify:
            text = build_notice(persona, event, due_text, "pre")
            mid = await _send(ws, t, text)
            t["pre_sent"] = True
            if mid and t.get("channel") == "group":
                t["remind_msg_id"] = mid
            changed = True
            logger.info(f"⏰ 提前提醒: {event} @ {due_text}")
        # 到点
        if not t.get("due_sent") and now >= due:
            text = build_notice(persona, event, due_text, "due")
            mid = await _send(ws, t, text)
            t["due_sent"] = True
            t.setdefault("last_bomb_at", now.strftime("%Y-%m-%d %H:%M:%S"))
            t.setdefault("confirmed", False)
            t.setdefault("bomb_count", 0)
            if mid and t.get("channel") == "group":
                t["remind_msg_id"] = mid
            changed = True
            logger.info(f"⏰ 到点提醒: {event} @ {due_text}")
        # 俏皮轰炸：到点已发且未确认，每隔 BOMB_INTERVAL_SEC 催一次
        if t.get("due_sent") and not t.get("confirmed"):
            if t.get("bomb_count", 0) >= BOMB_MAX_COUNT or                (now - due) > datetime.timedelta(minutes=BOMB_MAX_MINUTES):
                t["confirmed"] = True  # 自动放弃，停止轰炸
                changed = True
                continue
            last_s = t.get("last_bomb_at")
            try:
                last_dt = datetime.datetime.strptime(last_s, "%Y-%m-%d %H:%M:%S") if last_s else due
            except Exception:
                last_dt = due
            if (now - last_dt).total_seconds() >= BOMB_INTERVAL_SEC:
                text = build_bomb(persona, event, due_text, t.get("bomb_count", 0))
                mid = await _send(ws, t, text)
                t["bomb_count"] = t.get("bomb_count", 0) + 1
                t["last_bomb_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                if mid and t.get("channel") == "group":
                    t["remind_msg_id"] = mid
                changed = True
                logger.info(f"⏰ 轰炸#{t['bomb_count']}: {event} @ {due_text}")
    if changed:
        save_tasks(tasks)


async def _send(ws, task: dict, text: str) -> int | None:
    """发送提醒；返回 message_id（群聊用于匹配用户回复），失败/无注入返回 None"""
    fn = _sender.get("fn")
    if fn is not None:
        try:
            return await fn(ws, task, text)
        except Exception as exc:
            logger.warning(f"⏰ 提醒发送异常: {exc}")
            return None
    # 兜底直发（无 message_id）
    private_notice = task.get("notice_channel") == "private" or task.get("channel") == "private"
    if private_notice:
        await ws.send(json.dumps({
            "action": "send_private_msg",
            "params": {"user_id": task.get("user_id") or task.get("target_id"), "message": text},
        }))
    elif task.get("channel") == "group":
        await ws.send(json.dumps({
            "action": "send_group_msg",
            "params": {
                "group_id": task["target_id"],
                "message": f"[CQ:at,qq={task['user_id']}] {text}",
            },
        }))
    else:
        await ws.send(json.dumps({
            "action": "send_private_msg",
            "params": {"user_id": task["target_id"], "message": text},
        }))
    return None


def set_ws(ws) -> None:
    _ws["ws"] = ws


def set_sender(fn) -> None:
    """注入发送函数（main.py 提供，返回 message_id 用于群聊回复匹配）"""
    _sender["fn"] = fn


def _is_ack(text: str) -> bool:
    t = (text or "").strip().strip("~～。.!！ ")
    return bool(_ACK_RE.match(t))
