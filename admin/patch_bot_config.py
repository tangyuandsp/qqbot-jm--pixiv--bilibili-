# -*- coding: utf-8 -*-
"""给 config.py 追加运行时配置热加载（admin_config.json）"""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/opt/bilibot/config.py"

with io.open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

MARKER = "# ── 运行时配置"
if MARKER in content:
    print("config.py already patched, skip")
    sys.exit(0)

ADD = '''

# ── 运行时配置（管理面板 admin_config.json 热加载）──
import json as _json
import os as _os

ADMIN_CONFIG_PATH = "/opt/bilibot/admin/admin_config.json"

# 功能开关（id → bool），默认全部开启；新增 bot 功能时在这里加一条
FEATURES = {
    "bili": True,
    "jm": True,
    "pixiv": True,
    "voice": True,
}


def _read_admin_config():
    try:
        with open(ADMIN_CONFIG_PATH, "r", encoding="utf-8") as _f:
            data = _json.load(_f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reload_runtime():
    """从 admin_config.json 热加载可运行时修改的配置（带类型校验，防手改出错）"""
    data = _read_admin_config()
    if not data:
        return

    def _pick(key, default, checker):
        val = data.get(key, default)
        return val if checker(val) else default

    global ALLOWED_GROUPS, COMIC_ALLOWED_USERS, VOICE_CONTROL_USERS
    global COMIC_MAX_PDF_SIZE, MAX_FILE_SIZE, VOICE_MAX_CHARS
    global DEFAULT_VOICE, FEATURES

    ALLOWED_GROUPS = _pick("allowed_groups", ALLOWED_GROUPS,
                           lambda v: isinstance(v, list) and all(isinstance(x, int) for x in v))
    COMIC_ALLOWED_USERS = _pick("comic_allowed_users", COMIC_ALLOWED_USERS,
                                lambda v: isinstance(v, list) and all(isinstance(x, int) for x in v))
    VOICE_CONTROL_USERS = _pick("voice_control_users", VOICE_CONTROL_USERS,
                                lambda v: isinstance(v, list) and all(isinstance(x, int) for x in v))
    COMIC_MAX_PDF_SIZE = _pick("comic_max_pdf_size", COMIC_MAX_PDF_SIZE,
                               lambda v: isinstance(v, int) and v > 0)
    MAX_FILE_SIZE = _pick("max_file_size", MAX_FILE_SIZE,
                          lambda v: isinstance(v, int) and v > 0)
    VOICE_MAX_CHARS = _pick("voice_max_chars", VOICE_MAX_CHARS,
                            lambda v: isinstance(v, int) and 10 <= v <= 500)
    dv = data.get("default_voice")
    if dv in VOICES:
        DEFAULT_VOICE = dv

    feat = data.get("features")
    if isinstance(feat, dict):
        for k in FEATURES:
            if k in feat and isinstance(feat[k], bool):
                FEATURES[k] = feat[k]

    # 音色参数（语速/温度/断句/参考文本等）热更新到 VOICES 字典
    voices_ov = data.get("voices")
    if isinstance(voices_ov, dict):
        for name, ov in voices_ov.items():
            if name not in VOICES or not isinstance(ov, dict):
                continue
            for key in ("speed_factor", "temperature", "prompt_text",
                        "prompt_lang", "ref_audio", "text_split_method",
                        "fragment_interval"):
                if key not in ov:
                    continue
                if key in ("speed_factor", "temperature", "fragment_interval"):
                    val = ov[key]
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and 0.1 <= float(val) <= 5.0:
                        VOICES[name][key] = val
                elif isinstance(ov[key], str):
                    VOICES[name][key] = ov[key]


reload_runtime()
'''

with io.open(PATH, "a", encoding="utf-8") as f:
    f.write(ADD)
print("config.py patched OK")