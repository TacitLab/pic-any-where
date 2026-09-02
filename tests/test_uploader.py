import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pawlib import uploader

PNG_BYTES = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _write(tmpdir, name, data):
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


class SniffTest(unittest.TestCase):
    def test_png_ok(self):
        self.assertEqual(uploader.sniff_image(PNG_BYTES, "png"), "image/png")

    def test_jpg_ok(self):
        self.assertEqual(uploader.sniff_image(JPG_BYTES, "jpg"), "image/jpeg")

    def test_webp_ok(self):
        webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 16
        self.assertEqual(uploader.sniff_image(webp, "webp"), "image/webp")

    def test_webp_bad(self):
        with self.assertRaises(uploader.UploadError):
            uploader.sniff_image(b"RIFF" + b"\x00" * 4 + b"NOPE", "webp")

    def test_avif_ok(self):
        avif = b"\x00\x00\x00\x20ftypavif" + b"\x00" * 16
        self.assertEqual(uploader.sniff_image(avif, "avif"), "image/avif")

    def test_svg_ok(self):
        self.assertEqual(uploader.sniff_image(b'<svg xmlns="x"></svg>', "svg"),
                         "image/svg+xml")

    def test_magic_mismatch_rejected(self):
        with self.assertRaises(uploader.UploadError):
            uploader.sniff_image(b"not a png at all......", "png")

    def test_unknown_ext_rejected(self):
        with self.assertRaises(uploader.UploadError):
            uploader.sniff_image(b"MZ....", "exe")


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_validate(self):
        path = _write(self.tmp.name, "a.png", PNG_BYTES)
        data, ext, mime = uploader.read_and_validate(path, 25)
        self.assertEqual((ext, mime), ("png", "image/png"))
        self.assertEqual(data, PNG_BYTES)

    def test_oversize_rejected(self):
        path = _write(self.tmp.name, "big.png", PNG_BYTES)
        with self.assertRaises(uploader.UploadError):
            uploader.read_and_validate(path, 0)

    def test_missing_file(self):
        with self.assertRaises(uploader.UploadError):
            uploader.read_and_validate(os.path.join(self.tmp.name, "x.png"), 25)

    def test_jpeg_normalized_to_jpg(self):
        path = _write(self.tmp.name, "a.jpeg", JPG_BYTES)
        _, ext, _ = uploader.read_and_validate(path, 25)
        self.assertEqual(ext, "jpg")


class KeyTest(unittest.TestCase):
    def test_content_addressed_key(self):
        key = uploader.build_key(PNG_BYTES, "png", "i/")
        parts = key.split("/")
        self.assertEqual(parts[0], "i")
        self.assertEqual(len(parts), 4)  # i/YYYY/MM/hash.png
        self.assertTrue(parts[3].endswith(".png"))
        self.assertEqual(len(parts[3]), 16 + 4)

    def test_same_content_same_key(self):
        self.assertEqual(uploader.build_key(PNG_BYTES, "png", "i/"),
                         uploader.build_key(PNG_BYTES, "png", "i/"))

    def test_empty_prefix(self):
        key = uploader.build_key(PNG_BYTES, "png", "")
        self.assertFalse(key.startswith("/"))

    def test_sanitize_rejects_traversal(self):
        for bad in ("../x.png", "/abs.png", "a/../../b.png", "\\x.png", "a\nb.png"):
            with self.assertRaises(uploader.UploadError, msg=bad):
                uploader.sanitize_key(bad)

    def test_sanitize_ok(self):
        self.assertEqual(uploader.sanitize_key("img/2024/a b.png"),
                         "img/2024/a b.png")


class UrlTest(unittest.TestCase):
    def _profile(self, **kw):
        p = {"provider": "tencent", "region": "ap-guangzhou",
             "bucket": "imgs-1250000000"}
        p.update(kw)
        return p

    def test_custom_domain_preferred(self):
        url = uploader.public_url(
            self._profile(public_base_url="https://img.example.com"),
            "i/2024/01/ab.png")
        self.assertEqual(url, "https://img.example.com/i/2024/01/ab.png")

    def test_custom_domain_trailing_slash(self):
        url = uploader.public_url(
            self._profile(public_base_url="https://img.example.com/"),
            "a.png")
        self.assertEqual(url, "https://img.example.com/a.png")

    def test_default_virtual_host_url(self):
        url = uploader.public_url(self._profile(), "i/x.png")
        self.assertEqual(
            url,
            "https://imgs-1250000000.cos.ap-guangzhou.myqcloud.com/i/x.png")

    def test_key_url_encoded(self):
        url = uploader.public_url(
            self._profile(public_base_url="https://img.example.com"),
            "i/中文 图.png")
        self.assertIn("%E4%B8%AD%E6%96%87%20%E5%9B%BE.png", url)

    def test_http_public_base_rejected(self):
        with self.assertRaises(uploader.UploadError):
            uploader.public_url(
                self._profile(public_base_url="http://img.example.com"), "a.png")

    def test_path_style_default_url(self):
        p = self._profile(provider="custom", endpoint="minio.local:9000",
                          addressing_style="path", insecure_http=True)
        self.assertEqual(uploader.public_url(p, "a.png"),
                         "http://minio.local:9000/imgs-1250000000/a.png")

    def test_formats(self):
        self.assertEqual(uploader.format_output("u", "markdown", "x"), "![x](u)")
        self.assertEqual(uploader.format_output("u", "html", "x"),
                         '<img src="u" alt="x">')
        self.assertEqual(uploader.format_output("u", "url"), "u")


class UploadFlowTest(unittest.TestCase):
    """用假 client 验证 upload_file 串联逻辑（不发真实请求）。"""

    class FakeClient:
        def __init__(self):
            self.calls = []

        def put_object(self, key, data, content_type, cache_control=None, acl=None):
            self.calls.append((key, data, content_type, cache_control, acl))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_upload_file(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "key_prefix": "i/",
                   "cache_control": "public, max-age=1",
                   "provider": "aws", "region": "us-east-1", "bucket": "b",
                   "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        key, url = uploader.upload_file(client, profile, path)
        self.assertTrue(key.startswith("i/"))
        self.assertTrue(url.startswith("https://cdn.example.com/i/"))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][2], "image/png")

    def test_custom_key_gets_extension(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "provider": "aws", "region": "us-east-1",
                   "bucket": "b", "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        key, _ = uploader.upload_file(client, profile, path, key="avatar")
        self.assertEqual(key, "avatar.png")

    def test_prefix_override(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "key_prefix": "i/",
                   "provider": "aws", "region": "us-east-1", "bucket": "b",
                   "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        key, _ = uploader.upload_file(client, profile, path, prefix="blog/2024")
        self.assertTrue(key.startswith("blog/2024/"), key)

    def test_public_flag_sends_acl(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "provider": "aws", "region": "us-east-1",
                   "bucket": "b", "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        uploader.upload_file(client, profile, path, public=True)
        self.assertEqual(client.calls[0][4], "public-read")

    def test_profile_object_acl_applied(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "object_acl": "public-read",
                   "provider": "aws", "region": "us-east-1", "bucket": "b",
                   "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        uploader.upload_file(client, profile, path)
        self.assertEqual(client.calls[0][4], "public-read")

    def test_no_acl_by_default(self):
        path = _write(self.tmp.name, "pic.png", PNG_BYTES)
        profile = {"max_size_mb": 25, "provider": "aws", "region": "us-east-1",
                   "bucket": "b", "public_base_url": "https://cdn.example.com"}
        client = self.FakeClient()
        uploader.upload_file(client, profile, path)
        self.assertIsNone(client.calls[0][4])


class NormalizePrefixTest(unittest.TestCase):
    def test_strip_slashes(self):
        self.assertEqual(uploader.normalize_prefix("blog/imgs/"), "blog/imgs")
        self.assertEqual(uploader.normalize_prefix(""), "")
        self.assertEqual(uploader.normalize_prefix("//a//b//"), "a/b")

    def test_traversal_rejected(self):
        for bad in ("../x", "a/../b", ".", ".."):
            with self.assertRaises(uploader.UploadError, msg=bad):
                uploader.normalize_prefix(bad)


if __name__ == "__main__":
    unittest.main()
