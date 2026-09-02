"""配置文件读写与多 profile 管理。

配置路径（与 Skill 安装位置解耦）：
- 环境变量 PAW_CONFIG 可显式指定（主要供测试）
- Windows: %APPDATA%\\pic-any-where\\config.json
- 其他: ${XDG_CONFIG_HOME:-~/.config}/pic-any-where/config.json
"""

import json
import os
import sys

CONFIG_ENV = "PAW_CONFIG"

DEFAULTS = {
    "key_prefix": "i/",
    "cache_control": "public, max-age=31536000, immutable",
    "max_size_mb": 25,
    "insecure_http": False,
    "allow_file_credentials": False,
}

PROFILE_FIELDS = [
    "provider", "region", "bucket", "account_id", "endpoint",
    "addressing_style", "public_base_url", "key_prefix",
    "cache_control", "max_size_mb", "insecure_http",
    "allow_file_credentials", "aws_profile",
]


class ConfigError(Exception):
    pass


def config_path() -> str:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "pic-any-where", "config.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "pic-any-where", "config.json")


def load_config(path=None) -> dict:
    path = path or config_path()
    if not os.path.exists(path):
        return {"default_profile": None, "profiles": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"配置文件 {path} 读取失败：{e}")
    data.setdefault("default_profile", None)
    data.setdefault("profiles", {})
    return data


def save_config(data: dict, path=None) -> str:
    path = path or config_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # 配置文件可能包含敏感设置，收紧权限（Windows 上 chmod 无意义，忽略失败）
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def get_profile(data: dict, name=None) -> dict:
    profiles = data.get("profiles", {})
    name = name or data.get("default_profile")
    if not name:
        raise ConfigError("尚未配置任何 profile，请先运行：paw.py config init")
    if name not in profiles:
        raise ConfigError(f"profile '{name}' 不存在，已有：{', '.join(sorted(profiles)) or '（空）'}")
    profile = dict(DEFAULTS)
    profile.update(profiles[name])
    profile["_name"] = name
    return profile


def set_profile(data: dict, name: str, profile: dict, make_default=True) -> dict:
    clean = {k: v for k, v in profile.items()
             if k in PROFILE_FIELDS and v is not None}
    data.setdefault("profiles", {})[name] = clean
    if make_default or not data.get("default_profile"):
        data["default_profile"] = name
    return data


def check_config_permissions(path=None):
    """若配置里允许内嵌凭证，检查文件权限；返回警告信息列表。"""
    path = path or config_path()
    warnings = []
    if sys.platform == "win32" or not os.path.exists(path):
        return warnings
    mode = os.stat(path).st_mode & 0o777
    if mode & 0o077:
        warnings.append(
            f"配置文件 {path} 权限为 {oct(mode)}，建议执行 chmod 600 收紧")
    return warnings
