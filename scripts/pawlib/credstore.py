"""凭证管理：系统钥匙串存取 + 多来源解析。

解析优先级（高 → 低）：
1. 环境变量（PAW_* 或 AWS_*，支持 STS 临时凭证的 SESSION_TOKEN）
2. 系统钥匙串（macOS Keychain / libsecret / Windows 凭据管理器）
3. 已有的 ~/.aws/credentials（AWS 用户零配置复用）
4. 配置文件内嵌（默认拒绝，需 allow_file_credentials: true 且文件权限 0600）

任何情况下凭证都不会被打印到输出或日志。
"""

import configparser
import json
import os
import shutil
import subprocess
import sys
from typing import NamedTuple, Optional

SERVICE_NAME = "pic-any-where"


class CredentialError(Exception):
    pass


class Credentials(NamedTuple):
    access_key: str
    secret_key: str
    session_token: Optional[str] = None
    source: str = "unknown"


def redact(access_key: Optional[str]) -> str:
    if not access_key:
        return "(未配置)"
    return access_key[:4] + "****" if len(access_key) > 4 else "****"


# ---------------------------------------------------------------- 钥匙串后端

class KeychainBackend:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def get(self, profile: str) -> Optional[dict]:
        raise NotImplementedError

    def set(self, profile: str, data: dict) -> None:
        raise NotImplementedError

    def delete(self, profile: str) -> None:
        raise NotImplementedError


class MacOSKeychain(KeychainBackend):
    name = "macOS Keychain"

    def available(self):
        return sys.platform == "darwin" and shutil.which("security") is not None

    def set(self, profile, data):
        blob = json.dumps(data, ensure_ascii=False)
        # -U：已存在则更新。注：-w 参数在进程存续瞬间对同机用户可见，
        # 这是 security CLI 的固有限制，详见 references/security.md。
        r = subprocess.run(
            ["security", "add-generic-password", "-U",
             "-s", SERVICE_NAME, "-a", profile, "-w", blob],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise CredentialError(f"写入 macOS Keychain 失败：{r.stderr.strip()}")

    def get(self, profile):
        r = subprocess.run(
            ["security", "find-generic-password",
             "-s", SERVICE_NAME, "-a", profile, "-w"],
            capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout.strip())

    def delete(self, profile):
        subprocess.run(
            ["security", "delete-generic-password",
             "-s", SERVICE_NAME, "-a", profile],
            capture_output=True)


class LibsecretKeychain(KeychainBackend):
    name = "libsecret (secret-tool)"

    def available(self):
        return shutil.which("secret-tool") is not None

    def set(self, profile, data):
        blob = json.dumps(data, ensure_ascii=False)
        r = subprocess.run(
            ["secret-tool", "store",
             f"--label=pic-any-where ({profile})",
             "service", SERVICE_NAME, "profile", profile],
            input=blob, capture_output=True, text=True)
        if r.returncode != 0:
            raise CredentialError(f"写入 secret-tool 失败：{r.stderr.strip()}")

    def get(self, profile):
        r = subprocess.run(
            ["secret-tool", "lookup",
             "service", SERVICE_NAME, "profile", profile],
            capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout.strip())

    def delete(self, profile):
        subprocess.run(
            ["secret-tool", "clear",
             "service", SERVICE_NAME, "profile", profile],
            capture_output=True)


class WindowsCredManager(KeychainBackend):
    """Windows 凭据管理器（ctypes 调 Win32 CredRead/CredWrite，CRED_TYPE_GENERIC）。"""

    name = "Windows 凭据管理器"
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_ENTERPRISE = 3

    def available(self):
        return sys.platform == "win32"

    def _target(self, profile):
        return f"{SERVICE_NAME}/{profile}"

    def set(self, profile, data):
        import ctypes
        from ctypes import wintypes

        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        buf = ctypes.create_string_buffer(blob, len(blob))
        cred = CREDENTIAL()
        cred.Type = self._CRED_TYPE_GENERIC
        cred.TargetName = self._target(profile)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
        cred.Persist = self._CRED_PERSIST_ENTERPRISE
        if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise CredentialError(
                f"写入 Windows 凭据管理器失败（错误码 {ctypes.get_last_error()}）")

    def get(self, profile):
        import ctypes
        from ctypes import wintypes

        advapi32 = ctypes.windll.advapi32
        pcred = ctypes.c_void_p()
        if not advapi32.CredReadW(self._target(profile), self._CRED_TYPE_GENERIC,
                                  0, ctypes.byref(pcred)):
            return None
        try:
            # CREDENTIALW: CredentialBlobSize 在偏移 32（64 位）处——用结构体读取更稳
            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR),
                ]
            cred = ctypes.cast(pcred, ctypes.POINTER(CREDENTIAL)).contents
            blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            advapi32.CredFree(pcred)
        return json.loads(blob.decode("utf-8"))

    def delete(self, profile):
        import ctypes
        ctypes.windll.advapi32.CredDeleteW(self._target(profile),
                                           self._CRED_TYPE_GENERIC, 0)


def get_backend() -> Optional[KeychainBackend]:
    """返回当前平台可用的钥匙串后端，无可用后端返回 None。"""
    for cls in (MacOSKeychain, LibsecretKeychain, WindowsCredManager):
        backend = cls()
        try:
            if backend.available():
                return backend
        except Exception:
            continue
    return None


def store_credentials(profile: str, access_key: str, secret_key: str,
                      session_token: Optional[str] = None) -> str:
    """写入系统钥匙串，返回后端名称；无可用后端时抛 CredentialError。"""
    backend = get_backend()
    if backend is None:
        raise CredentialError(
            "当前系统没有可用的钥匙串后端（macOS security / Linux secret-tool / "
            "Windows 凭据管理器）。可改用环境变量提供凭证，或在配置中显式设置 "
            "allow_file_credentials: true 后手写配置（不推荐）。")
    backend.set(profile, {
        "access_key": access_key,
        "secret_key": secret_key,
        "session_token": session_token,
    })
    return backend.name


def delete_credentials(profile: str) -> bool:
    backend = get_backend()
    if backend is None:
        return False
    backend.delete(profile)
    return True


# ---------------------------------------------------------------- 凭证解析

def _from_env(env) -> Optional[Credentials]:
    for prefix in ("PAW", "AWS"):
        ak = env.get(f"{prefix}_ACCESS_KEY_ID")
        sk = env.get(f"{prefix}_SECRET_ACCESS_KEY")
        if ak and sk:
            return Credentials(ak, sk, env.get(f"{prefix}_SESSION_TOKEN"),
                               source=f"环境变量 {prefix}_*")
    return None


def _from_aws_credentials_file(section: str) -> Optional[Credentials]:
    path = os.path.expanduser("~/.aws/credentials")
    if not os.path.exists(path):
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return None
    if not parser.has_section(section):
        return None
    ak = parser.get(section, "aws_access_key_id", fallback=None)
    sk = parser.get(section, "aws_secret_access_key", fallback=None)
    if ak and sk:
        return Credentials(ak, sk,
                           parser.get(section, "aws_session_token", fallback=None),
                           source=f"~/.aws/credentials [{section}]")
    return None


def resolve_credentials(profile: dict, env=None) -> Credentials:
    """按优先级解析凭证；找不到时抛 CredentialError 并给出指引。"""
    env = os.environ if env is None else env

    creds = _from_env(env)
    if creds:
        return creds

    backend = get_backend()
    if backend is not None:
        try:
            data = backend.get(profile.get("_name") or "default")
        except Exception:
            data = None
        if data and data.get("access_key") and data.get("secret_key"):
            return Credentials(data["access_key"], data["secret_key"],
                               data.get("session_token"),
                               source=f"系统钥匙串（{backend.name}）")

    creds = _from_aws_credentials_file(profile.get("aws_profile") or "default")
    if creds:
        return creds

    if profile.get("allow_file_credentials"):
        ak, sk = profile.get("access_key"), profile.get("secret_key")
        if ak and sk:
            return Credentials(ak, sk, profile.get("session_token"),
                               source="配置文件（明文，不推荐）")

    raise CredentialError(
        "未找到可用凭证。请选择其一：\n"
        "  1. 运行 paw.py config set-credential 将 AK/SK 写入系统钥匙串（推荐）\n"
        "  2. 设置环境变量 PAW_ACCESS_KEY_ID / PAW_SECRET_ACCESS_KEY"
        "（临时凭证另加 PAW_SESSION_TOKEN）\n"
        "  3. AWS 用户可直接复用 ~/.aws/credentials")
