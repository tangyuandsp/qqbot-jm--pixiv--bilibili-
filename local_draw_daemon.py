# -*- coding: utf-8 -*-
"""本地 SD 绘图隧道守护（Windows 上运行）

作用：
1. 确保本地 Stable Diffusion WebUI (127.0.0.1:7860, --api) 在线
2. 建立 SSH 反向隧道：服务器 127.0.0.1:17860 → 本地 127.0.0.1:7860

这样服务器上的 bot 就能通过 http://127.0.0.1:17860 调用本地 SD 出图。
用法: python local_draw_daemon.py   （建议开机自启）
"""
import socket
import subprocess
import sys
import time

# Windows 控制台/重定向默认 GBK，强制 UTF-8 避免 emoji 崩
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVER = "root@115.29.233.209"
REMOTE_PORT = 17860
LOCAL_PORT = 7860


def _local_sd_alive() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=2)
        s.close()
        return True
    except Exception:
        return False


def main():
    print("🔗 本地 SD 隧道守护启动")
    print(f"   本地 SD: http://127.0.0.1:{LOCAL_PORT}（需已启动 WebUI --api）")
    print(f"   服务器映射: {REMOTE_PORT} → 本地 {LOCAL_PORT}")
    print(f"   目标: {SERVER}")
    print()

    retry = 5
    while True:
        if not _local_sd_alive():
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 本地 SD 未启动，请先运行 webui-user.bat")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] 本地 SD 在线，建立隧道...")
            proc = subprocess.Popen(
                [
                    "ssh",
                    "-o", "ServerAliveInterval=30",
                    "-o", "ServerAliveCountMax=3",
                    "-o", "ExitOnForwardFailure=yes",
                    "-R", f"{REMOTE_PORT}:127.0.0.1:{LOCAL_PORT}",
                    "-N",
                    SERVER,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(4)
            if proc.poll() is not None:
                err = proc.stderr.read()
                print(f"[{time.strftime('%H:%M:%S')}] ❌ 隧道启动失败: {err.strip()}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ✅ 隧道已建立 (PID={proc.pid})")
                proc.wait()
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 隧道断开，{retry}s 后重连")
                time.sleep(retry)
                retry = min(retry * 2, 60)
                continue
        time.sleep(retry)
        retry = min(retry * 2, 60)


if __name__ == "__main__":
    main()
