# ============================================================
# QQ 群聊 B站视频下载机器人 — 配置文件（服务器版）
# ============================================================

# ── 正向 WebSocket：连接本机 NapCatQQ Docker 容器 ──
NAPCAT_WS_URL = "ws://localhost:3001"

# 视频临时下载目录
TEMP_DIR = "/opt/bilibot/temp_videos"

# 最大文件大小限制（100MB）
MAX_FILE_SIZE = 100 * 1024 * 1024

# 群白名单：只处理这些群的 B站链接
ALLOWED_GROUPS = [111111111]  # 在这里填白名单群号  # 汪汪队登duan郎 + 第二群

# ── Pixiv 功能 ──
# Pixiv refresh_token（从浏览器 Cookie 或 OAuth 获取）
# 获取方式: https://github.com/upbit/pixivpy/issues/158
PIXIV_REFRESH_TOKEN = "your_pixiv_refresh_token"
# QQ 号白名单：只有这些 QQ 号的 /jm 命令才会生效
COMIC_ALLOWED_USERS = [10001, 10002]  # 私聊白名单 QQ  # 你的大号 + 机器人号

# 漫画下载临时目录（服务器上）
COMIC_TEMP_DIR = "/opt/bilibot/temp_videos/comic"

# 漫画 PDF 最大文件大小（80MB，QQ 群文件上限约 100MB）
COMIC_MAX_PDF_SIZE = 80 * 1024 * 1024

# B站 API 请求头
BILIBILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 重连间隔（秒）
RECONNECT_DELAY = 5

# ── 语音功能（GPT-SoVITS 多音色，经反向隧道连接本机）──
# 本地电脑运行 voice/voice_daemon.py，隧道把服务器 9881 转发到本机 9880
TTS_URL = "http://127.0.0.1:9881/tts"
# 默认音色（/say 不带音色名时使用）
DEFAULT_VOICE = "爱莉希雅"

# 4 种可用音色：权重路径/参考音频均在本地电脑上，TTS 请求原样透传
VOICES = {
    "爱莉希雅": {
        "id": "elisia",
        "gpt_weights": "E:/qq-bili-bot/voice/models/elisia_v2/gpt.ckpt",
        "sovits_weights": "E:/qq-bili-bot/voice/models/elisia_v2/sovits.pth",
        "ref_audio": "E:/qq-bili-bot/voice/models/elisia_v2/refs/ref_normal2.wav",
        "prompt_text": "爱莉希雅的贴心提示，你可以尽情依赖爱莉希雅，而她也会以全部的真心来回应你。",
        "prompt_lang": "zh",
        "speed_factor": 0.9,
        "temperature": 0.7,
    },
    "洛琪希": {
        "id": "roxy",
        "gpt_weights": "E:/qq-bili-bot/voice/models/roxy/Roxy_Pro.ckpt",
        "sovits_weights": "E:/qq-bili-bot/voice/models/roxy/Roxy_Pro.pth",
        "ref_audio": "E:/qq-bili-bot/voice/models/roxy/ref_roxy_ohayo.wav",
        "prompt_text": "おはようございます、ルディ。その…",
        "prompt_lang": "ja",
        "speed_factor": 0.85,
        "temperature": 0.7,
    },
    "神里绫华": {
        "id": "ayaka",
        "gpt_weights": "E:/qq-bili-bot/voice/models/ayaka/gpt.ckpt",
        "sovits_weights": "E:/qq-bili-bot/voice/models/ayaka/sovits.pth",
        "ref_audio": "E:/qq-bili-bot/voice/models/ayaka/ref.wav",
        "prompt_text": "看来，你们能理解我的心情了，既然这样，不知能否再考虑一下…",
        "prompt_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.7,
        "text_split_method": "cut0",
        "fragment_interval": 0.1,
    },
    "流萤": {
        "id": "firefly",
        "gpt_weights": "E:/qq-bili-bot/voice/models/firefly_v4/gpt.ckpt",
        "sovits_weights": "E:/qq-bili-bot/voice/models/firefly_v4/sovits.pth",
        "ref_audio": "E:/qq-bili-bot/voice/models/firefly_v4/refs/ref_happy.wav",
        "prompt_text": "我还知道，你们经常在银河各地到处旅行。",
        "prompt_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.7,
    },
    '希儿': {
        "id": 'seele',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/希儿白/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/希儿白/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/希儿白/refs/三/我吗？可是布罗尼亚姐姐和提安娜相处更久，了解更多吧。.wav',
        "prompt_text": '我吗？可是布罗尼亚姐姐和提安娜相处更久，了解更多吧。',
        "prompt_lang": "zh",
        "speed_factor": 0.9,
        "temperature": 0.7,
    },
    '布洛妮娅': {
        "id": 'bronya',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/布洛妮娅/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/布洛妮娅/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/布洛妮娅/refs/那当然了，即使在千羽学院的废墟，芽衣也并没有真的做错什么。.wav',
        "prompt_text": '那当然了，即使在千羽学院的废墟，芽衣也并没有真的做错什么。',
        "prompt_lang": "zh",
        "speed_factor": 0.9,
        "temperature": 0.7,
    },
    '花火': {
        "id": 'huahuo',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/花火_dj/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/花火_dj/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/花火_dj/refs/花火参考音频-真是个冷血的家伙，嘿，我们说不定很聊得来哦。.wav',
        "prompt_text": '真是个冷血的家伙，嘿，我们说不定很聊得来哦。',
        "prompt_lang": "zh",
        "speed_factor": 0.92,
        "temperature": 0.82,
    },
    '风堇': {
        "id": 'fengjin',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/风堇/gpt_v3.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/风堇/sovits_v2.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/风堇/refs/不辛苦！伤员们都很配合治疗，能让大家健健康康回家去，我就心满意足啦。.wav',
        "prompt_text": '不辛苦！伤员们都很配合治疗，能让大家健健康康回家去，我就心满意足啦。',
        "prompt_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.7,
    },
    '胡桃': {
        "id": 'hutao',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/胡桃/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/胡桃/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/胡桃/ref.wav',
        "prompt_text": '本堂主略施小计，你就败下阵来了，嘿嘿。',
        "prompt_lang": "zh",
        "speed_factor": 1.05,
        "temperature": 1.0,
    },
    '刻晴': {
        "id": 'keqing',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/刻晴/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/刻晴/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/刻晴/ref.wav',
        "prompt_text": '这「七圣召唤」虽说是游戏，但对局之中也隐隐有策算谋略之理。',
        "prompt_lang": "zh",
        "speed_factor": 1.0,
        "temperature": 0.8,
    },
    '甘雨': {
        "id": 'ganyu',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/甘雨/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/甘雨/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/甘雨/ref.wav',
        "prompt_text": '但只要最后落在具体的「人」身上，那，我可以想办法。',
        "prompt_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.7,
    },
    '三月七': {
        "id": 'march7',
        "gpt_weights": 'E:/qq-bili-bot/voice/models/三月七/gpt.ckpt',
        "sovits_weights": 'E:/qq-bili-bot/voice/models/三月七/sovits.pth',
        "ref_audio": 'E:/qq-bili-bot/voice/models/三月七/ref.wav',
        "prompt_text": '名字是我自己取的，大家也叫我三月、小三月…你呢？你想叫我什么？',
        "prompt_lang": "zh",
        "speed_factor": 0.82,
        "temperature": 0.82,
    },
}
VOICE_NAMES = list(VOICES.keys())
# 语音临时目录（服务器上，NapCat 已挂载 temp_videos）
VOICE_SAY_DIR = "/opt/bilibot/temp_videos/say"
# 单条语音最大字数（超出直接拒绝，保护 CPU/显卡）
VOICE_MAX_CHARS = 80

# /sayto 指定发送语音的管理员白名单（只有这些 QQ 能用）
VOICE_CONTROL_USERS = [10001, 10002]  # 语音管理员 QQ

# 日志
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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
    "ai": True,
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
