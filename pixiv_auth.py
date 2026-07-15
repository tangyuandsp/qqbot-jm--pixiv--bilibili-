#!/usr/bin/env python3
"""
获取 Pixiv refresh_token 工具
用法: python pixiv_auth.py
然后浏览器打开提示的 URL，登录 Pixiv，把跳转后的完整 URL 粘贴回来
"""
import hashlib
import secrets
import urllib.parse
import webbrowser
import requests

CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"

def s256(code_verifier):
    return hashlib.sha256(code_verifier.encode()).digest()

def base64_urlencode(data):
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def main():
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64_urlencode(s256(code_verifier))

    login_url = (
        "https://app-api.pixiv.net/web/v1/login"
        f"?code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&client=pixiv-android"
    )

    print("=" * 50)
    print("请在浏览器打开以下 URL 并登录 Pixiv:")
    print()
    print(login_url)
    print()
    print("登录成功后页面会跳转到一个空白页")
    print("复制浏览器地址栏的完整 URL，粘贴到这里:")
    print("=" * 50)

    webbrowser.open(login_url)  # 尝试自动打开浏览器

    callback_url = input("\n粘贴回调 URL: ").strip()
    parsed = urllib.parse.urlparse(callback_url)
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [None])[0]

    if not code:
        print("❌ 未从 URL 中找到 code，请检查粘贴的 URL 是否完整")
        return

    response = requests.post(
        "https://oauth.secure.pixiv.net/auth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "include_policy": "true",
            "redirect_uri": REDIRECT_URI,
        },
        headers={"User-Agent": "PixivAndroidApp/5.0.0"},
        timeout=15,
    )
    data = response.json()
    if "refresh_token" in data:
        print()
        print("=" * 50)
        print("✅ 成功！你的 refresh_token:")
        print()
        print(data["refresh_token"])
        print()
        print("把这个 token 发给 Claude，我帮你配置到机器人里")
        print("=" * 50)
    else:
        print(f"❌ 获取失败: {data}")

if __name__ == "__main__":
    main()
