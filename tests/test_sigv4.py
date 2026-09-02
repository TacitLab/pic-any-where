"""用 AWS 官方文档中的 SigV4 示例验证签名正确性。

官方示例（IAM 文档）：https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html
"""

import unittest
from datetime import datetime, timezone

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pawlib import sigv4


class SigV4OfficialVectorTest(unittest.TestCase):
    def test_aws_doc_example_signature(self):
        # AWS 官方文档示例：GET iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08
        headers = sigv4.sign(
            "GET", "/",
            [("Action", "ListUsers"), ("Version", "2010-05-08")],
            {
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
                "host": "iam.amazonaws.com",
            },
            sigv4.sha256_hex(b""),
            access_key="AKIDEXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            region="us-east-1",
            service="iam",
            request_datetime=datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc),
        )
        auth = headers["Authorization"]
        self.assertTrue(auth.startswith("AWS4-HMAC-SHA256 "))
        self.assertIn("Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request", auth)
        self.assertIn("SignedHeaders=content-type;host;x-amz-date", auth)
        self.assertIn(
            "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7",
            auth,
        )

    def test_derive_signing_key_known_value(self):
        # 同一官方示例的中间值
        key = sigv4.derive_signing_key(
            "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            "20150830", "us-east-1", "iam")
        self.assertEqual(
            key.hex(),
            "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9",
        )

    def test_canonical_request_matches_doc(self):
        canonical, signed = sigv4.build_canonical_request(
            "GET", "/",
            [("Action", "ListUsers"), ("Version", "2010-05-08")],
            {
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
                "host": "iam.amazonaws.com",
                "x-amz-date": "20150830T123600Z",
            },
            sigv4.sha256_hex(b""),
        )
        self.assertEqual(signed, "content-type;host;x-amz-date")
        expected = (
            "GET\n"
            "/\n"
            "Action=ListUsers&Version=2010-05-08\n"
            "content-type:application/x-www-form-urlencoded; charset=utf-8\n"
            "host:iam.amazonaws.com\n"
            "x-amz-date:20150830T123600Z\n"
            "\n"
            "content-type;host;x-amz-date\n"
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        self.assertEqual(canonical, expected)

    def test_uri_encoding_keeps_slash_and_encodes_special(self):
        self.assertEqual(sigv4._uri_encode_path("i/2024/a b.png"), "/i/2024/a%20b.png")
        self.assertEqual(sigv4._uri_encode_path("/中文/图.png"), "/%E4%B8%AD%E6%96%87/%E5%9B%BE.png")

    def test_query_sorted_and_encoded(self):
        qs = sigv4._normalize_query([("b", "2"), ("a", "x y"), ("a", "1")])
        self.assertEqual(qs, "a=1&a=x%20y&b=2")

    def test_session_token_header_added(self):
        headers = sigv4.sign(
            "PUT", "/k.png", [],
            {"host": "example.com"},
            sigv4.sha256_hex(b"x"),
            access_key="AK", secret_key="SK", region="auto",
            session_token="token123",
        )
        self.assertEqual(headers["x-amz-security-token"], "token123")
        self.assertIn("x-amz-security-token", headers["Authorization"])


if __name__ == "__main__":
    unittest.main()
