# ============================================================
# 漫画下载模块
# 功能: 使用 jmcomic 库下载漫画并输出为 PDF
# ============================================================

import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

_download_executor = ThreadPoolExecutor(max_workers=2)

# jmcomic 需要的目录配置
# 使用已挂载到 NapCat 容器的目录
_COMIC_DIR = "/opt/bilibot/temp_videos/comic"
_PDF_DIR = "/opt/bilibot/temp_videos/comic"


def _do_download_comic(comic_id: str) -> str:
    """
    同步下载漫画并转换为 PDF。
    在线程池中运行。

    参数:
        comic_id: 漫画 ID（纯数字）

    返回:
        PDF 文件绝对路径

    异常:
        RuntimeError: 下载或转换失败
    """
    import jmcomic

    album_id = str(int(comic_id))  # 确保是有效数字
    work_dir = os.path.join(_COMIC_DIR, album_id)
    os.makedirs(work_dir, exist_ok=True)

    # 构造配置：下载到 work_dir，结束后自动导出 PDF
    option = jmcomic.create_option_by_str(f"""
download:
  image:
    suffix: .jpg
  dir:
    rule: Bdir_Pindex
    base_dir: "{work_dir}"
  threading:
    image: 6
    photo: 1
plugins:
  after_album:
    - plugin: img2pdf
      kwargs:
        pdf_dir: "{_PDF_DIR}"
        filename_rule: "[JM{{Aid}}] {{Atitle}}.pdf"
        delete_original_file: true
""")

    try:
        album, _dler = jmcomic.download_album(album_id, option=option)
    except Exception as e:
        # 清理可能的残留
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(f"漫画下载失败: {e}") from e

    # PDF 文件已由 img2pdf 插件生成到 _PDF_DIR
    pdf_filename = f"[JM{album_id}] {album.name}.pdf"
    # 过滤文件名中的非法字符
    import re
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', pdf_filename)
    pdf_path = os.path.join(_PDF_DIR, safe_name)

    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return os.path.abspath(pdf_path)

    # 如果 pdf 名字不同，搜索一下
    for f in os.listdir(_PDF_DIR):
        if f.startswith(f"[JM{album_id}]") and f.endswith(".pdf"):
            return os.path.abspath(os.path.join(_PDF_DIR, f))

    raise RuntimeError("PDF 生成失败：未找到输出文件")


async def download_comic(comic_id: str) -> str:
    """异步封装"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_download_executor, _do_download_comic, comic_id)
