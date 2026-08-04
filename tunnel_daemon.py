#!/usr/bin/env python3
# ============================================================
# Pixiv 隧道守护进程（Windows 上运行）
# 自动建立并维护到服务器的 SSH 反向隧道
# 用法: python tunnel_daemon.py
# ============================================================

import subprocess
import time
import sys

SERVER = "root@YOUR_SERVER_IP"  # TODO: 替换为你的服务器地址
REMOTE_PORT = 10091
LOCAL_PORT = 10090

def main():
    print(f"🔗 Pixiv 隧道守护启动")
    print(f"   本地代理: 127.0.0.1:{LOCAL_PORT}")
    print(f"   服务器映射: {REMOTE_PORT} → 本地 {LOCAL_PORT}")
    print(f"   目标: {SERVER}")
    print()

    retry_delay = 5

    while True:
        print(f"[{time.strftime('%H:%M:%S')}] 建立隧道...")
        proc = subprocess.Popen(
            [
                "ssh",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes",
                "-R", f"{REMOTE_PORT}:127.0.0.1:{LOCAL_PORT}",
                "-N",  # 不执行远程命令
                SERVER,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        # 等 3 秒看是不是立刻挂了
        time.sleep(3)
        if proc.poll() is not None:
            err = proc.stderr.read()
            print(f"[{time.strftime('%H:%M:%S')}] ❌ 隧道启动失败: {err.strip()}")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ✅ 隧道已建立 (PID={proc.pid})")
            proc.wait()
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 隧道断开，{retry_delay}s 后重连...")

        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60)  # 退避，最多 60s

if __name__ == "__main__":
    main()
