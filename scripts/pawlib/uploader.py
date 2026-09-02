"""上传管线：文件校验 → 内容寻址命名 → 上传 → 生成访问 URL。"""

import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import quote

from . import providers


class UploadError(Exception):
    pass


# 扩展名 → (MIME, 魔数校验)。SVG 为文本格式，单独处理。
_IMAGE_SIGNATURES = {
    "png": ("image/png", [b"\x89PNG\r\n\x1a\n"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "gif": ("image/gif", [b"GIF87a", b"GIF89a"]),
    "webp": ("image/webp", [b"RIFF"]),  # 需额外校验第 8-12 字节为 WEBP
    "ico": ("image/x-icon", [b"\x00\x00\x01\x00"]),
    "avif": ("image/avif", []),  # 通过 ftyp box 校验
}


def sniff_image(data: bytes, ext: str):
    """返回 MIME 类型；内容不像声明的图片格式时抛 UploadError。"""
    ext = ext.lower()
    if ext == "svg":
        head = data[:1024].lstrip()
        if b"<svg" in head or (head.startswith(b"<?xml") and b"<svg" in data[:4096]):
            return "image/svg+xml"
        raise UploadError("扩展名为 .svg 但内容不含 <svg> 标签")
    if ext not in _IMAGE_SIGNATURES:
        allowed = ", ".join(sorted(_IMAGE_SIGNATURES) + ["svg"])
        raise UploadError(f"不支持的图片格式 '.{ext}'，支持：{allowed}")
    mime, magics = _IMAGE_SIGNATURES[ext]
    if ext == "webp":
        if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
            raise UploadError("文件内容不是有效的 WebP 图片")
        return mime
    if ext == "avif":
        if not (len(data) > 12 and data[4:8] == b"ftyp"
                and data[8:12] in (b"avif", b"avis")):
            raise UploadError("文件内容不是有效的 AVIF 图片")
        return mime
    if not any(data.startswith(m) for m in magics):
        raise UploadError(f"文件内容与 .{ext} 格式不符（魔数校验失败）")
    return mime


def read_and_validate(path: str, max_size_mb: int):
    """读取文件并做大小/格式校验，返回 (data, ext, mime)。"""
    if not os.path.isfile(path):
        raise UploadError(f"文件不存在：{path}")
    max_bytes = int(max_size_mb) * 1024 * 1024
    size = os.path.getsize(path)
    if size > max_bytes:
        raise UploadError(
            f"文件过大：{size / 1024 / 1024:.1f}MB 超过上限 {max_size_mb}MB"
            "（可在 profile 中调整 max_size_mb）")
    if size == 0:
        raise UploadError("空文件，拒绝上传")
    with open(path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if not ext:
        raise UploadError("文件缺少扩展名，无法判断图片格式")
    mime = sniff_image(data, ext)
    if ext == "jpeg":
        ext = "jpg"
    return data, ext, mime


def build_key(data: bytes, ext: str, prefix: str = "i/") -> str:
    """内容寻址命名：{prefix}{YYYY/MM}/{sha256前16位}.{ext}

    同内容天然去重、防覆盖、不泄露原始文件名。
    """
    digest = hashlib.sha256(data).hexdigest()[:16]
    date_path = datetime.now(timezone.utc).strftime("%Y/%m")
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{date_path}/{digest}.{ext}" if prefix \
        else f"{date_path}/{digest}.{ext}"


def sanitize_key(key: str) -> str:
    """校验用户自定义 key，拒绝路径穿越与危险字符。"""
    if not key or len(key) > 512:
        raise UploadError("key 为空或过长（>512）")
    if key.startswith(("/", "\\")) or ".." in key.split("/"):
        raise UploadError("key 含路径穿越成分，已拒绝")
    if any(ord(c) < 32 for c in key):
        raise UploadError("key 含控制字符，已拒绝")
    return key


def quote_key(key: str) -> str:
    return quote(key, safe="/-_.~")


def public_url(profile: dict, key: str) -> str:
    """生成访问 URL：优先自定义域名（CDN/源站域名），否则厂商默认域名。"""
    quoted = quote_key(key)
    base = (profile.get("public_base_url") or "").rstrip("/")
    if base:
        if not base.startswith("https://") and not (
                base.startswith("http://") and profile.get("insecure_http")):
            raise UploadError(
                f"public_base_url 必须使用 https://：{base}")
        return f"{base}/{quoted}"
    return providers.default_object_url(profile, quoted)


def format_output(url: str, fmt: str, alt: str = "image") -> str:
    if fmt == "markdown":
        return f"![{alt}]({url})"
    if fmt == "html":
        return f'<img src="{url}" alt="{alt}">'
    return url


def normalize_prefix(prefix) -> str:
    """规范化 key 前缀：去除多余斜杠，拒绝路径穿越与控制字符。"""
    if not prefix:
        return ""
    parts = [p for p in str(prefix).split("/") if p]
    if any(p in (".", "..") for p in parts) or any(ord(c) < 32 for c in prefix):
        raise UploadError("prefix 含路径穿越成分或控制字符，已拒绝")
    return "/".join(parts)


def upload_file(client, profile: dict, path: str, key=None, prefix=None, public=False):
    """完整上传流程，返回 (key, url)。

    prefix 非 None 时覆盖 profile 的 key_prefix；public=True 或 profile 配置
    object_acl=public-read 时，上传带 x-amz-acl: public-read（要求桶允许对象级 ACL）。
    """
    data, ext, mime = read_and_validate(path, profile.get("max_size_mb", 25))
    if key:
        key = sanitize_key(key)
        if not os.path.splitext(key)[1]:
            key = f"{key}.{ext}"
    else:
        effective = prefix if prefix is not None else profile.get("key_prefix", "i/")
        key = build_key(data, ext, normalize_prefix(effective))
    # 优先级：--public 参数 > profile 的 object_acl 配置
    acl = "public-read" if public else profile.get("object_acl")
    client.put_object(key, data, mime, profile.get("cache_control"), acl=acl)
    return key, public_url(profile, key)
