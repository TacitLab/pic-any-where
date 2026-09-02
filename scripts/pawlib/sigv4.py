"""AWS Signature Version 4 签名实现（纯标准库）。

同时被 AWS S3、腾讯云 COS、阿里云 OSS（S3 兼容模式）、Cloudflare R2 等使用。
参考：https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html
"""

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote

_ALGORITHM = "AWS4-HMAC-SHA256"
_EMPTY_PAYLOAD_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _uri_encode_path(path: str) -> str:
    """按 SigV4 规则编码路径：逐段编码，保留 '/' 分隔符。"""
    if not path.startswith("/"):
        path = "/" + path
    return quote(path, safe="-_.~/")


def _normalize_query(query) -> str:
    """query 为 [(name, value), ...]，按 SigV4 规则排序编码。"""
    pairs = [
        (quote(str(k), safe="-_.~"), quote(str(v), safe="-_.~"))
        for k, v in query
    ]
    pairs.sort()
    return "&".join(f"{k}={v}" for k, v in pairs)


def _normalize_headers(headers: dict):
    """返回 (canonical_headers_str, signed_headers_str)。header 名小写排序、值压缩空白。"""
    items = {}
    for name, value in headers.items():
        key = name.strip().lower()
        # 压缩连续空白（SigV4 要求）
        val = " ".join(str(value).strip().split())
        if key in items:
            items[key] = items[key] + "," + val
        else:
            items[key] = val
    names = sorted(items)
    canonical = "".join(f"{n}:{items[n]}\n" for n in names)
    return canonical, ";".join(names)


def derive_signing_key(secret_key: str, date_stamp: str, region: str, service: str = "s3") -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def build_canonical_request(method, path, query, headers, payload_hash):
    canonical_headers, signed_headers = _normalize_headers(headers)
    canonical_request = "\n".join([
        method.upper(),
        _uri_encode_path(path),
        _normalize_query(query),
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    return canonical_request, signed_headers


def sign(method, path, query, headers, payload_hash, *,
         access_key, secret_key, region, service="s3",
         request_datetime=None, session_token=None):
    """对请求做 SigV4 签名，返回需要附加的 headers（含 Authorization）。

    headers 中必须已包含 host 与 x-amz-date（若未提供 request_datetime 会自动补）。
    """
    if request_datetime is None:
        request_datetime = datetime.now(timezone.utc)
    amz_date = request_datetime.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = request_datetime.strftime("%Y%m%d")

    headers = dict(headers)
    headers.setdefault("x-amz-date", amz_date)
    if session_token:
        headers["x-amz-security-token"] = session_token

    canonical_request, signed_headers = build_canonical_request(
        method, path, query, headers, payload_hash)

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        _ALGORITHM,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = derive_signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    headers["Authorization"] = (
        f"{_ALGORITHM} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def presign_url(scheme, host, path, query, *,
                access_key, secret_key, region, service="s3",
                expires=3600, request_datetime=None, session_token=None):
    """生成预签名 GET URL（查询参数方式签名）。"""
    if request_datetime is None:
        request_datetime = datetime.now(timezone.utc)
    amz_date = request_datetime.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = request_datetime.strftime("%Y%m%d")
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

    params = [
        ("X-Amz-Algorithm", _ALGORITHM),
        ("X-Amz-Credential", f"{access_key}/{credential_scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(int(expires))),
        ("X-Amz-SignedHeaders", "host"),
    ]
    if session_token:
        params.append(("X-Amz-Security-Token", session_token))
    params.extend(query)

    canonical_request, _ = build_canonical_request(
        "GET", path, params, {"host": host}, "UNSIGNED-PAYLOAD")
    string_to_sign = "\n".join([
        _ALGORITHM,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signing_key = derive_signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    params.append(("X-Amz-Signature", signature))
    return f"{scheme}://{host}{_uri_encode_path(path)}?{_normalize_query(params)}"
