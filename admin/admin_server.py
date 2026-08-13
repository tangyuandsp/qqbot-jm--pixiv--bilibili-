#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BiliBot 管理面板后端（独立进程，不侵入 bot 主逻辑）
=====================================================
职责：
  1. 提供 REST API 给前端读取/修改 admin_config.json
  2. bot 每 30 秒热加载 admin_config.json（白名单/限制/音色参数/功能开关）
  3. 展示服务器状态、bot 状态、日志

扩展性设计：
  - 功能开关 FEATURE_META：新增功能时在这里加一条，前端“功能”页自动出现开关
  - 配置项在 PUT /api/config 中做白名单校验，新增配置项只需在校验函数里加一行
  - 静态前端放在 static/，新增页面/选项卡无需改后端
"""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/bilibot")  # 复用 bot 的 config.py（纯常量模块，无副作用）
import config as bot_config
import ai_handler
import daily_greeting

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
CONFIG_FILE = BASE / "admin_config.json"
BOT_LOG = Path("/var/log/bilibot.log")

app = FastAPI(title="BiliBot Admin", docs_url=None, redoc_url=None)

# 功能清单：新增 bot 功能时在此追加一条 {id, name, desc, icon}
FEATURE_META = [
    {"id": "bili", "name": "B站视频下载", "icon": "🎬",
     "desc": "识别群里的 B站链接，自动下载最低画质并回传"},
    {"id": "jm", "name": "禁漫漫画", "icon": "📚",
     "desc": "/jm 下载漫画 PDF、查看详情/封面/排行"},
    {"id": "pixiv", "name": "Pixiv 插画", "icon": "🎨",
     "desc": "/pixiv 下载原图、排行榜、搜索插画"},
    {"id": "voice", "name": "语音合成", "icon": "🎙️",
     "desc": "/say 四种音色语音条（爱莉希雅/洛琪希/神里绫华/流萤）"},
    {"id": "ai", "name": "AI 语音对话", "icon": "🤖",
     "desc": "/ai 与角色人设语音对话，/persona 切换人设"},
]


# ----------------------------------------------------------
# 配置读写
# ----------------------------------------------------------

def load_admin_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_admin_config(cfg: dict) -> None:
    tmp = CONFIG_FILE.with_name("admin_config.json.tmp")
    tmp.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(CONFIG_FILE)


def ensure_config() -> dict:
    """首次运行：用 bot 当前默认值生成 admin_config.json"""
    cfg = load_admin_config()
    if cfg:
        return cfg
    cfg = {
        "admin_token": secrets.token_urlsafe(24),
        "allowed_groups": list(bot_config.ALLOWED_GROUPS),
        "comic_allowed_users": list(bot_config.COMIC_ALLOWED_USERS),
        "voice_control_users": list(bot_config.VOICE_CONTROL_USERS),
        "comic_max_pdf_size": bot_config.COMIC_MAX_PDF_SIZE,
        "max_file_size": bot_config.MAX_FILE_SIZE,
        "voice_max_chars": bot_config.VOICE_MAX_CHARS,
        "default_voice": bot_config.DEFAULT_VOICE,
        "features": {f["id"]: True for f in FEATURE_META},
        "voices": {},
    }
    save_admin_config(cfg)
    os.chmod(CONFIG_FILE, 0o600)
    return cfg


def get_token() -> str:
    return ensure_config().get("admin_token", "")


# ----------------------------------------------------------
# 鉴权
# ----------------------------------------------------------

def check_auth(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {get_token()}":
        raise HTTPException(status_code=401, detail="unauthorized")


# ----------------------------------------------------------
# 系统信息（纯 stdlib，避免依赖 psutil）
# ----------------------------------------------------------

def _cpu_percent() -> float:
    def _read():
        with open("/proc/stat") as f:
            parts = f.readline().split()
        nums = [int(x) for x in parts[1:8]]
        return sum(nums), nums[3]  # total, idle
    t1, i1 = _read()
    time.sleep(0.4)
    t2, i2 = _read()
    d_total = t2 - t1
    d_idle = i2 - i1
    return round(100.0 * (1 - d_idle / d_total), 1) if d_total else 0.0


def _mem_mb():
    total = avail = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) // 1024
    return total, avail


def _disk_gb():
    s = os.statvfs("/")
    total = s.f_frsize * s.f_blocks
    free = s.f_frsize * s.f_bavail
    return total // (1024 ** 3), free // (1024 ** 3)


def _uptime():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def _tail_log(n: int = 100) -> list:
    if not BOT_LOG.exists():
        return ["(日志文件不存在: /var/log/bilibot.log)"]
    with open(BOT_LOG, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        block = 8192
        data = b""
        while size > 0 and data.count(b"\n") < n:
            size = max(0, size - block)
            f.seek(size)
            data = f.read(block) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-n:]


def _bot_ws_status() -> str:
    try:
        lines = _tail_log(60)
    except Exception:
        return "unknown"
    for line in reversed(lines):
        if "已连接到 NapCatQQ" in line or "开始监听" in line:
            return "connected"
        if "连接失败" in line or "WebSocket 断开" in line or "重连中" in line:
            return "disconnected"
    return "unknown"


def _service_active(name: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


# ----------------------------------------------------------
# 音色合并：config.py 全量定义 + admin_config.json 覆盖
# ----------------------------------------------------------

def merged_voices() -> dict:
    bot_config.reload_runtime()  # 让 admin 进程也应用最新覆盖
    overrides = load_admin_config().get("voices", {})
    out = {}
    for name, v in bot_config.VOICES.items():
        item = dict(v)
        item["name"] = name
        ov = overrides.get(name, {})
        for key in ("speed_factor", "temperature", "prompt_text", "prompt_lang",
                    "text_split_method", "fragment_interval", "ref_audio"):
            if key in ov:
                item[key] = ov[key]
        out[name] = item
    return out


def save_voice_overrides(updates: dict) -> None:
    cfg = ensure_config()
    voices = cfg.setdefault("voices", {})
    for name, ov in updates.items():
        if name not in bot_config.VOICES or not isinstance(ov, dict):
            continue
        entry = voices.setdefault(name, {})
        for key in ("speed_factor", "temperature", "prompt_text", "prompt_lang",
                    "text_split_method", "fragment_interval", "ref_audio"):
            if key in ov:
                val = ov[key]
                if key in ("speed_factor", "temperature", "fragment_interval"):
                    if (not isinstance(val, (int, float))
                            or isinstance(val, bool)
                            or not (0.1 <= float(val) <= 5.0)):
                        raise HTTPException(
                            status_code=400,
                            detail=f"{name}.{key} 必须是 0.1~5 之间的数字",
                        )
                elif not isinstance(val, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{name}.{key} 必须是字符串",
                    )
                entry[key] = val
    save_admin_config(cfg)


# ----------------------------------------------------------
# API
# ----------------------------------------------------------

@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "bilibot-admin", "time": time.time()}


@app.get("/api/status")
def api_status(request: Request):
    check_auth(request)
    mem_total, mem_avail = _mem_mb()
    disk_total, disk_free = _disk_gb()
    return {
        "bot_active": _service_active("bilibot"),
        "ws_status": _bot_ws_status(),
        "cpu_percent": _cpu_percent(),
        "mem_total_mb": mem_total,
        "mem_avail_mb": mem_avail,
        "disk_total_gb": disk_total,
        "disk_free_gb": disk_free,
        "uptime_seconds": int(_uptime()),
        "default_voice": bot_config.DEFAULT_VOICE,
        "voice_count": len(bot_config.VOICES),
        "log_preview": _tail_log(3),
    }


@app.get("/api/config")
def api_get_config(request: Request):
    check_auth(request)
    return ensure_config()


@app.put("/api/config")
async def api_put_config(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    cfg = ensure_config()

    # 白名单校验：新配置项在这里加一行
    def _int_list(key):
        val = body.get(key)
        if val is None:
            return
        if not isinstance(val, list) or not all(isinstance(x, int) for x in val):
            raise HTTPException(status_code=400, detail=f"{key} 必须是数字列表")
        cfg[key] = val

    def _pos_int(key):
        val = body.get(key)
        if val is None:
            return
        if not isinstance(val, int) or val <= 0:
            raise HTTPException(status_code=400, detail=f"{key} 必须是正整数")
        cfg[key] = val

    _int_list("allowed_groups")
    _int_list("comic_allowed_users")
    _int_list("voice_control_users")
    _pos_int("comic_max_pdf_size")
    _pos_int("max_file_size")
    _pos_int("voice_max_chars")

    if "default_voice" in body:
        if body["default_voice"] not in bot_config.VOICES:
            raise HTTPException(status_code=400, detail="未知音色")
        cfg["default_voice"] = body["default_voice"]

    if "admin_token" in body and isinstance(body["admin_token"], str) and len(body["admin_token"]) >= 16:
        cfg["admin_token"] = body["admin_token"]

    if "voices" in body and isinstance(body["voices"], dict):
        save_voice_overrides(body["voices"])

    if "features" in body and isinstance(body["features"], dict):
        feat = cfg.setdefault("features", {})
        for fid, enabled in body["features"].items():
            if isinstance(enabled, bool):
                feat[fid] = enabled

    save_admin_config(cfg)
    return {"ok": True, "config": cfg,
            "hint": "白名单/限制/音色参数将在 30 秒内自动生效；默认音色需重启 bot"}


@app.get("/api/voices")
def api_get_voices(request: Request):
    check_auth(request)
    return merged_voices()


@app.put("/api/voices")
async def api_put_voices(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    save_voice_overrides(body)
    return {"ok": True, "voices": merged_voices()}


@app.get("/api/features")
def api_get_features(request: Request):
    check_auth(request)
    cfg = ensure_config()
    feat = cfg.get("features", {})
    return [
        {"id": f["id"], "name": f["name"], "icon": f["icon"], "desc": f["desc"],
         "enabled": feat.get(f["id"], True)}
        for f in FEATURE_META
    ]


@app.put("/api/features")
async def api_put_features(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    cfg = ensure_config()
    feat = cfg.setdefault("features", {})
    for fid, enabled in body.items():
        if isinstance(enabled, bool):
            feat[fid] = enabled
    save_admin_config(cfg)
    return {"ok": True}


@app.get("/api/logs")
def api_logs(request: Request, lines: int = 200):
    check_auth(request)
    lines = max(10, min(lines, 500))
    return {"lines": _tail_log(lines)}


@app.post("/api/restart")
def api_restart(request: Request):
    check_auth(request)
    try:
        r = subprocess.run(
            ["systemctl", "restart", "bilibot"],
            capture_output=True, text=True, timeout=30,
        )
        return {"ok": r.returncode == 0, "detail": r.stderr.strip()[:200]}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:200]}


# ----------------------------------------------------------
# AI 设置
# ----------------------------------------------------------

@app.get("/api/ai")
def api_get_ai(request: Request):
    check_auth(request)
    personas = [
        {"id": pid, "voice": ai_handler.get_voice_for_persona(pid),
         "greeting": ai_handler.get_greeting(pid)}
        for pid in ai_handler.list_personas()
    ]
    return {
        "personas": personas,
        "current": ai_handler.get_current_persona(),
        "context_length": ai_handler.get_context_length(),
        "turn_budget": ai_handler.get_turn_budget(),
        "voice_reply": ai_handler.get_voice_reply(),
        "queue_max": ai_handler.get_queue_max(),
    }


@app.put("/api/ai")
async def api_put_ai(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    if "persona" in body:
        val = body["persona"]
        if val is None or val == "off":
            ai_handler.set_current_persona(None)
        elif isinstance(val, str) and val in ai_handler.list_personas():
            ai_handler.set_current_persona(val)
        else:
            raise HTTPException(status_code=400, detail="未知人设")
    if "context_length" in body:
        n = body["context_length"]
        if not isinstance(n, int) or not (2 <= n <= 50):
            raise HTTPException(status_code=400, detail="context_length 必须是 2~50 的整数")
        ai_handler.set_context_length(n)
    if "turn_budget" in body:
        n = body["turn_budget"]
        if not isinstance(n, int) or not (1 <= n <= 5):
            raise HTTPException(status_code=400, detail="turn_budget 必须是 1~5 的整数")
        ai_handler.set_turn_budget(n)
    if "voice_reply" in body:
        if not isinstance(body["voice_reply"], bool):
            raise HTTPException(status_code=400, detail="voice_reply 必须是布尔值")
        ai_handler.set_voice_reply(body["voice_reply"])
    if "queue_max" in body:
        n = body["queue_max"]
        if not isinstance(n, int) or not (1 <= n <= 10):
            raise HTTPException(status_code=400, detail="queue_max 必须是 1~10 的整数")
        ai_handler.set_queue_max(n)
    return {
        "personas": [
            {"id": pid, "voice": ai_handler.get_voice_for_persona(pid),
             "greeting": ai_handler.get_greeting(pid)}
            for pid in ai_handler.list_personas()
        ],
        "current": ai_handler.get_current_persona(),
        "context_length": ai_handler.get_context_length(),
        "turn_budget": ai_handler.get_turn_budget(),
        "voice_reply": ai_handler.get_voice_reply(),
        "queue_max": ai_handler.get_queue_max(),
    }


@app.get("/api/ai/affection")
def api_get_affection(request: Request):
    check_auth(request)
    return ai_handler.get_affection_all()


@app.put("/api/ai/affection")
async def api_put_affection(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    persona = body.get("persona")
    conv = body.get("conv")
    user = body.get("user")
    if persona not in ai_handler.list_personas():
        raise HTTPException(status_code=400, detail="未知人设")
    if not isinstance(conv, str) or not conv:
        raise HTTPException(status_code=400, detail="conv 不能为空")
    if not isinstance(user, int) or user <= 0:
        raise HTTPException(status_code=400, detail="user 必须是 QQ 号")
    if body.get("reset"):
        ai_handler.reset_affection(persona, conv, user)
    else:
        value = body.get("value")
        if not isinstance(value, int) or not (0 <= value <= 100):
            raise HTTPException(status_code=400, detail="value 必须是 0~100 的整数")
        ai_handler.set_affection(persona, conv, user, value)
    return {"ok": True}


@app.get("/api/daily")
def api_get_daily(request: Request):
    check_auth(request)
    return {
        "enabled": daily_greeting.get_enabled(),
        "targets": daily_greeting.get_targets(),
        "slots": [
            {"id": k, "time": "%d:%02d" % (h, m), "name": n}
            for k, (h, m, n) in daily_greeting.SLOTS.items()
        ],
    }


@app.put("/api/daily")
async def api_put_daily(request: Request):
    check_auth(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be object")
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise HTTPException(status_code=400, detail="enabled 必须是布尔值")
        daily_greeting.set_enabled(body["enabled"])
    if "add_target" in body:
        t = body["add_target"]
        if (not isinstance(t, dict) or t.get("type") not in ("private", "group")
                or not isinstance(t.get("id"), int)):
            raise HTTPException(status_code=400, detail="add_target 格式错误")
        daily_greeting.add_target(t["type"], t["id"])
    if "remove_target" in body:
        t = body["remove_target"]
        if (not isinstance(t, dict) or t.get("type") not in ("private", "group")
                or not isinstance(t.get("id"), int)):
            raise HTTPException(status_code=400, detail="remove_target 格式错误")
        daily_greeting.remove_target(t["type"], t["id"])
    return {
        "enabled": daily_greeting.get_enabled(),
        "targets": daily_greeting.get_targets(),
        "slots": [
            {"id": k, "time": "%d:%02d" % (h, m), "name": n}
            for k, (h, m, n) in daily_greeting.SLOTS.items()
        ],
    }


# ----------------------------------------------------------
# 静态前端（放在最后挂载，避免吞掉 /api 路由）
# ----------------------------------------------------------
if not STATIC.exists():
    STATIC.mkdir(parents=True)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
