#!/usr/bin/env python3
# ============================================================
# BiliBot 视频临时目录清理脚本
# 每 12 小时清理一次 /opt/bilibot/temp_videos/
# ============================================================
# 使用方式:
#   nohup python3 cleaner.py > /var/log/bilibot_cleaner.log 2>&1 &
#
# Drop-in replacement: 也可以用 crontab 替代这个脚本
#   0 */12 * * * find /opt/bilibot/temp_videos/ -type f -delete
# ============================================================

import datetime
import glob
import logging
import os
import sys
import time

TEMP_DIR = "/opt/bilibot/temp_videos"
CLEAN_INTERVAL_HOURS = 12

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Cleaner: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("Cleaner")


def cleanup():
    """删除 TEMP_DIR 下所有文件"""
    if not os.path.isdir(TEMP_DIR):
        logger.warning(f"目录不存在: {TEMP_DIR}")
        return

    files = glob.glob(os.path.join(TEMP_DIR, "*"))
    if not files:
        logger.info("目录已空，跳过清理")
        return

    total_size = 0
    deleted = 0
    for fp in files:
        try:
            size = os.path.getsize(fp)
            os.remove(fp)
            total_size += size
            deleted += 1
        except OSError as e:
            logger.error(f"删除失败: {fp} — {e}")

    size_mb = total_size / (1024 * 1024)
    logger.info(f"清理完成: 删除 {deleted} 个文件, 释放 {size_mb:.1f} MB")


def main():
    logger.info(f"清理守护启动, 目录: {TEMP_DIR}, 间隔: {CLEAN_INTERVAL_HOURS}h")

    # 启动时先清一次
    cleanup()

    while True:
        now = datetime.datetime.now()
        # 每 12 小时的下一次执行: 00:00 或 12:00
        next_hour = (now.hour // CLEAN_INTERVAL_HOURS + 1) * CLEAN_INTERVAL_HOURS
        target = now.replace(hour=next_hour % 24, minute=0, second=0, microsecond=0)
        if next_hour >= 24:
            target += datetime.timedelta(days=1)

        wait = (target - now).total_seconds()
        logger.info(f"下次清理: {target.strftime('%Y-%m-%d %H:%M:%S')} ({wait/3600:.1f}h 后)")
        time.sleep(wait)
        cleanup()


if __name__ == "__main__":
    main()
