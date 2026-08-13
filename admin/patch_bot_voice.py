# -*- coding: utf-8 -*-
"""给 voice_handler.py 接入动态默认音色（跟随管理面板配置）"""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/opt/bilibot/voice_handler.py"

with io.open(PATH, "r", encoding="utf-8") as f:
    c = f.read()


def rep(old, new, label):
    global c
    if old not in c:
        raise SystemExit(f"[{label}] marker not found")
    c = c.replace(old, new, 1)


# 1. 改为模块访问 config.DEFAULT_VOICE（支持热加载默认音色）
rep(
    "from config import DEFAULT_VOICE, TTS_URL, VOICES, VOICE_SAY_DIR",
    "import config\nfrom config import TTS_URL, VOICES, VOICE_SAY_DIR",
    "import",
)

# 2. 默认音色改为 None = 跟随管理面板配置
rep(
    '# 当前默认音色（/voice 切换后，/say 不带音色名时使用它）\n_default_voice = {"name": DEFAULT_VOICE}',
    '# 当前默认音色（/voice 切换后 /say 使用它；None = 跟随管理面板配置的默认音色）\n_default_voice = {"name": None}',
    "default init",
)

# 3. get_current_voice 动态回退到配置
rep(
    '''def get_current_voice() -> str:
    """当前默认音色（/voice 切换后 /say 使用的音色）"""
    return _default_voice["name"]''',
    '''def get_current_voice() -> str:
    """当前默认音色（/voice 切换后 /say 使用它；未切换则跟随管理面板配置）"""
    return _default_voice["name"] or config.DEFAULT_VOICE''',
    "get_current_voice",
)

# 4. generate_voice 使用 get_current_voice
rep(
    '    name = resolve_voice(voice_name) or _default_voice["name"]',
    "    name = resolve_voice(voice_name) or get_current_voice()",
    "generate_voice",
)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(c)
print("voice_handler.py patched OK")