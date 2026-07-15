# ============================================================
# 资源清理模块
# 功能: 定期清理超过 1 天的临时文件（视频/pixiv/comic）
# ============================================================

import os
import shutil
import time
import logging

from config import TEMP_DIR

logger = logging.getLogger("BiliBot.cleanup")

# 清理间隔：超过此时间（秒）的文件被删除
MAX_AGE_SECONDS = 24 * 60 * 60  # 1 天

# 清理策略：
#   - temp_videos/*.mp4  视频文件（直接删除）
#   - temp_videos/pixiv/ 整个目录（rmtree，里面全是缩略图）
#   - temp_videos/comic/ 整个目录（rmtree，里面全是 PDF + 封面）
#   - temp_videos/*.jpg  根目录封面图片（直接删除）


def _is_old(filepath: str) -> bool:
    """检查文件是否超过 MAX_AGE_SECONDS"""
    try:
        mtime = os.path.getmtime(filepath)
        return (time.time() - mtime) > MAX_AGE_SECONDS
    except OSError:
        return False


def cleanup_temp_dir() -> None:
    """
    清理 temp_videos 下超过 1 天的所有临时文件。
    程序启动时和每日 15:00 调用。
    """
    if not os.path.isdir(TEMP_DIR):
        return

    now = time.time()
    deleted_count = 0
    deleted_bytes = 0

    # ── 1. 清理根目录媒体文件（mp4, jpg 等）──
    for fname in os.listdir(TEMP_DIR):
        fpath = os.path.join(TEMP_DIR, fname)
        if os.path.isfile(fpath) and _is_old(fpath):
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                deleted_count += 1
                deleted_bytes += size
                logger.info(f"  🗑 删除: {fname} ({size/1024:.0f}KB)")
            except OSError as e:
                logger.warning(f"  ⚠ 删除失败: {fname}: {e}")

    # ── 2. 清理 pixiv 子目录（整体删除）──
    pixiv_dir = os.path.join(TEMP_DIR, "pixiv")
    if os.path.isdir(pixiv_dir) and _is_old(pixiv_dir):
        try:
            size = _dir_size(pixiv_dir)
            shutil.rmtree(pixiv_dir)
            deleted_count += 1
            deleted_bytes += size
            logger.info(f"  🗑 删除: pixiv/ ({size/(1024*1024):.1f}MB)")
        except OSError as e:
            logger.warning(f"  ⚠ 删除 pixiv/ 失败: {e}")

    # ── 3. 清理 comic 子目录（整体删除）──
    comic_dir = os.path.join(TEMP_DIR, "comic")
    if os.path.isdir(comic_dir) and _is_old(comic_dir):
        try:
            size = _dir_size(comic_dir)
            shutil.rmtree(comic_dir)
            deleted_count += 1
            deleted_bytes += size
            logger.info(f"  🗑 删除: comic/ ({size/(1024*1024):.1f}MB)")
        except OSError as e:
            logger.warning(f"  ⚠ 删除 comic/ 失败: {e}")

    if deleted_count > 0:
        logger.info(f"🧹 清理完成: {deleted_count} 项, {deleted_bytes/(1024*1024):.1f}MB")
    else:
        logger.debug("🧹 无需清理（所有文件均在1天内）")


def _dir_size(path: str) -> int:
    """递归计算目录总大小（字节）"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total
