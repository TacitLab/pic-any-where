"""端到端集成测试：起本地假 S3 HTTP 服务，验证 paw 全链路（签名→PUT→URL）。"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAW = os.path.join(REPO, "scripts", "paw.py")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
received = {}


class FakeS3(http.server.BaseHTTPRequestHandler):
    def _handle(self):
        if "Authorization" not in self.headers:
            self.send_error(403, "missing auth")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        received[self.command] = (self.path, dict(self.headers), body)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = do_GET = do_HEAD = do_DELETE = _handle

    def log_message(self, *a):
        pass


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), FakeS3)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = {
            "default_profile": "test",
            "profiles": {
                "test": {
                    "provider": "custom",
                    "endpoint": f"127.0.0.1:{self.port}",
                    "addressing_style": "path",
                    "region": "us-east-1",
                    "bucket": "testbucket",
                    "public_base_url": "https://img.example.com",
                    "insecure_http": True,
                }
            },
        }
        self.config_path = os.path.join(self.tmp.name, "config.json")
        with open(self.config_path, "w") as f:
            json.dump(config, f)
        self.env = dict(os.environ, **{
            "PAW_CONFIG": self.config_path,
            "PAW_ACCESS_KEY_ID": "TESTAK",
            "PAW_SECRET_ACCESS_KEY": "TESTSK",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *argv):
        return subprocess.run([sys.executable, PAW, *argv],
                              env=self.env, capture_output=True, text=True)

    def test_doctor_and_upload_flow(self):
        r = self._run("doctor", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("全部通过", r.stdout)

        pic = os.path.join(self.tmp.name, "pic.png")
        with open(pic, "wb") as f:
            f.write(PNG)
        r = self._run("upload", pic, "--format", "markdown")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.strip()
        self.assertTrue(out.startswith("![pic](https://img.example.com/i/"), out)
        self.assertTrue(out.endswith(".png)"), out)

        # 假服务器收到了带签名的 PUT，路径为 path 风格，内容一致
        self.assertIn("PUT", received)
        path, headers, body = received["PUT"]
        self.assertTrue(path.startswith("/testbucket/i/"), path)
        self.assertEqual(body, PNG)
        self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 "))
        self.assertIn("Credential=TESTAK/", headers["Authorization"])
        self.assertEqual(headers["Content-Type"], "image/png")

        # key 可从输出 URL 反解，url 子命令应给出同一链接
        key = out.split("https://img.example.com/", 1)[1].rstrip(")")
        r = self._run("url", key)
        self.assertEqual(r.stdout.strip(), f"https://img.example.com/{key}")

    def test_rm(self):
        r = self._run("rm", "i/x.png")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(received["DELETE"][0], "/testbucket/i/x.png")

    def test_upload_with_prefix_and_public(self):
        pic = os.path.join(self.tmp.name, "p.png")
        with open(pic, "wb") as f:
            f.write(PNG)
        r = self._run("upload", pic, "--prefix", "blog/2024", "--public")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://img.example.com/blog/2024/", r.stdout)
        path, headers, body = received["PUT"]
        self.assertTrue(path.startswith("/testbucket/blog/2024/"), path)
        lower = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lower.get("x-amz-acl"), "public-read")

    def test_config_set_then_show(self):
        r = self._run("config", "set", "--name", "second",
                      "--provider", "aws", "--region", "us-east-1",
                      "--bucket", "b2", "--object-acl", "public-read")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run("config", "show")
        self.assertIn("[second]", r.stdout)
        self.assertIn("object_acl = public-read", r.stdout)
        # 部分更新：只改 region，其余保留
        r = self._run("config", "set", "--name", "second", "--region", "us-west-2")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.config_path) as f:
            saved = json.load(f)
        self.assertEqual(saved["profiles"]["second"]["region"], "us-west-2")
        self.assertEqual(saved["profiles"]["second"]["bucket"], "b2")

    def test_config_set_requires_bucket(self):
        r = self._run("config", "set", "--name", "bad", "--provider", "aws")
        self.assertEqual(r.returncode, 1)
        self.assertIn("bucket", r.stderr)


if __name__ == "__main__":
    unittest.main()
