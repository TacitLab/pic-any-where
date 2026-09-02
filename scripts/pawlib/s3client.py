"""S3 兼容对象存储 HTTP 客户端（纯 urllib，SigV4 签名）。"""

import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from . import providers, sigv4

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


class S3Error(Exception):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def _sanitize(text: str) -> str:
    """清理错误信息，避免回显任何请求头/签名材料，并限制长度。"""
    if not text:
        return ""
    for marker in ("Authorization", "Signature", "Credential", "X-Amz"):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()[:300]


class S3Client:
    def __init__(self, profile: dict, creds, timeout=DEFAULT_TIMEOUT):
        self.profile = profile
        self.creds = creds
        self.timeout = timeout
        # 默认强制 HTTPS；仅当显式设置 insecure_http 时允许 http（本地 MinIO 等）
        self.scheme = "http" if profile.get("insecure_http") else "https"
        self.host, self.base_path = providers.build_host_and_base_path(profile)
        self.region = providers.resolve_signing_region(profile)
        if not self.host:
            raise S3Error("endpoint 解析失败")

    # ------------------------------------------------------------ 底层请求

    def _object_path(self, key=None):
        base = self.base_path.rstrip("/")
        if key is None:
            return base + "/"
        return f"{base}/{key}"

    def request(self, method, key=None, query=None, data=b"", extra_headers=None,
                allowed=(200, 204, 206)):
        path = self._object_path(key)
        payload_hash = sigv4.sha256_hex(data)
        headers = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
        }
        if extra_headers:
            headers.update(extra_headers)
        # 签名会补 x-amz-date / Authorization / 可能的 token 头
        signed = sigv4.sign(
            method, path, query or [], headers, payload_hash,
            access_key=self.creds.access_key,
            secret_key=self.creds.secret_key,
            region=self.region, service="s3",
            session_token=self.creds.session_token)

        url = f"{self.scheme}://{self.host}{sigv4._uri_encode_path(path)}"
        if query:
            url += "?" + sigv4._normalize_query(query)

        last_err = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(url, data=data if method != "GET" else None,
                                         method=method)
            for name, value in signed.items():
                req.add_header(name, value)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    if resp.status in allowed:
                        return resp.status, body
                    raise S3Error(f"HTTP {resp.status}", status=resp.status)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                code = None
                try:
                    root = ET.fromstring(body)
                    code = root.findtext("Code")
                    message = root.findtext("Message")
                except ET.ParseError:
                    message = ""
                if e.code >= 500 and attempt < MAX_RETRIES - 1:
                    last_err = S3Error(_sanitize(message) or f"HTTP {e.code}",
                                       status=e.code, code=code)
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise S3Error(
                    f"{code or 'HTTP ' + str(e.code)}: {_sanitize(message) or e.reason}",
                    status=e.code, code=code)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = S3Error(f"网络错误：{_sanitize(str(e.reason if hasattr(e, 'reason') else e))}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise last_err
        raise last_err or S3Error("请求失败")

    # ------------------------------------------------------------ 高层操作

    def put_object(self, key, data: bytes, content_type, cache_control=None, acl=None):
        headers = {"Content-Type": content_type,
                   "Content-Length": str(len(data))}
        if cache_control:
            headers["Cache-Control"] = cache_control
        if acl:
            headers["x-amz-acl"] = acl
        self.request("PUT", key=key, data=data, extra_headers=headers)

    def delete_object(self, key):
        self.request("DELETE", key=key)

    def head_bucket(self):
        """HEAD Bucket，验证连通性与凭证有效性。"""
        self.request("HEAD", key=None)

    def list_objects(self, prefix="", max_keys=100):
        query = [("list-type", "2"), ("max-keys", str(max_keys))]
        if prefix:
            query.append(("prefix", prefix))
        _, body = self.request("GET", key=None, query=query)
        root = ET.fromstring(body)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        keys = []
        for item in root.iter(f"{ns}Contents"):
            keys.append({
                "key": item.findtext(f"{ns}Key"),
                "size": int(item.findtext(f"{ns}Size") or 0),
                "last_modified": item.findtext(f"{ns}LastModified"),
            })
        return keys

    def presign_get(self, key, expires=3600):
        return sigv4.presign_url(
            self.scheme, self.host, self._object_path(key), [],
            access_key=self.creds.access_key,
            secret_key=self.creds.secret_key,
            region=self.region, service="s3",
            expires=expires,
            session_token=self.creds.session_token)
