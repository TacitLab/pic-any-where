"""主流 S3 兼容厂商的预设：endpoint 模板、寻址风格、常用 region。

用户只需选择厂商并填写 region / bucket，endpoint 自动推导；
每个 profile 仍可用 endpoint / addressing_style 字段覆盖默认值。
"""

PROVIDERS = {
    "aws": {
        "display": "AWS S3",
        "endpoint_template": "s3.{region}.amazonaws.com",
        "addressing_style": "virtual",
        "default_region": "us-east-1",
        "common_regions": ["us-east-1", "us-west-2", "eu-west-1",
                           "ap-southeast-1", "ap-northeast-1"],
        "needs_account_id": False,
        "hint": "标准 S3。region 即签名 region。",
    },
    "tencent": {
        "display": "腾讯云 COS",
        "endpoint_template": "cos.{region}.myqcloud.com",
        "addressing_style": "virtual",
        "default_region": "ap-guangzhou",
        "common_regions": ["ap-guangzhou", "ap-shanghai", "ap-beijing",
                           "ap-chengdu", "ap-singapore"],
        "needs_account_id": False,
        "hint": "bucket 需带 APPID 后缀，如 mybucket-1250000000。",
    },
    "aliyun": {
        "display": "阿里云 OSS（S3 兼容模式）",
        "endpoint_template": "oss-{region}.aliyuncs.com",
        "addressing_style": "virtual",
        "default_region": "cn-hangzhou",
        "common_regions": ["cn-hangzhou", "cn-shanghai", "cn-beijing",
                           "cn-shenzhen", "ap-southeast-1"],
        "needs_account_id": False,
        "hint": "OSS 官方兼容 S3 协议，直接用 OSS endpoint + RAM 用户 AK/SK。",
    },
    "cloudflare": {
        "display": "Cloudflare R2",
        "endpoint_template": "{account_id}.r2.cloudflarestorage.com",
        "addressing_style": "virtual",
        "default_region": "auto",
        "common_regions": ["auto"],
        "needs_account_id": True,
        "hint": "region 固定为 auto；需要 Cloudflare 账户 ID。",
    },
    "qiniu": {
        "display": "七牛云 Kodo",
        "endpoint_template": "s3.{region}.qiniucs.com",
        "addressing_style": "virtual",
        "default_region": "cn-east-1",
        "common_regions": ["cn-east-1", "cn-north-1", "cn-south-1",
                           "us-north-1", "ap-southeast-1"],
        "needs_account_id": False,
        "hint": "Kodo 提供 S3 兼容接口，region 形如 cn-east-1。",
    },
    "custom": {
        "display": "自定义 / MinIO / 其他 S3 兼容服务",
        "endpoint_template": None,  # 必须自填 endpoint
        "addressing_style": "path",  # MinIO 等通常用 path 风格
        "default_region": "us-east-1",
        "common_regions": [],
        "needs_account_id": False,
        "hint": "自填 endpoint；本地 MinIO 可开启 insecure_http。",
    },
}


class ProviderError(ValueError):
    pass


def get_provider(name):
    if name not in PROVIDERS:
        raise ProviderError(
            f"未知厂商 '{name}'，可选：{', '.join(sorted(PROVIDERS))}")
    return PROVIDERS[name]


def resolve_endpoint(profile: dict) -> str:
    """由 profile 推导 endpoint host（不含 scheme）。"""
    if profile.get("endpoint"):
        ep = profile["endpoint"]
        for scheme in ("https://", "http://"):
            if ep.startswith(scheme):
                ep = ep[len(scheme):]
        return ep.rstrip("/")
    provider = get_provider(profile.get("provider", "custom"))
    template = provider["endpoint_template"]
    if not template:
        raise ProviderError("provider=custom 必须在 profile 中显式配置 endpoint")
    region = profile.get("region") or provider["default_region"]
    endpoint = template.replace("{region}", region)
    if "{account_id}" in endpoint:
        account_id = profile.get("account_id")
        if not account_id:
            raise ProviderError(
                f"厂商 {profile.get('provider')} 需要在 profile 中配置 account_id")
        endpoint = endpoint.replace("{account_id}", account_id)
    return endpoint


def resolve_signing_region(profile: dict) -> str:
    provider = get_provider(profile.get("provider", "custom"))
    return profile.get("region") or provider["default_region"]


def resolve_addressing_style(profile: dict) -> str:
    if profile.get("addressing_style") in ("virtual", "path"):
        return profile["addressing_style"]
    return get_provider(profile.get("provider", "custom"))["addressing_style"]


def build_host_and_base_path(profile: dict):
    """返回 (host, base_path)。virtual 风格 bucket 进 host；path 风格进路径。"""
    endpoint = resolve_endpoint(profile)
    bucket = profile.get("bucket")
    if not bucket:
        raise ProviderError("profile 缺少 bucket 配置")
    style = resolve_addressing_style(profile)
    if style == "virtual":
        return f"{bucket}.{endpoint}", "/"
    return endpoint, f"/{bucket}"


def default_object_url(profile: dict, quoted_key: str) -> str:
    """未配置自定义域名时的默认访问 URL（virtual-host 风格）。"""
    scheme = "http" if profile.get("insecure_http") else "https"
    host, base_path = build_host_and_base_path(profile)
    return f"{scheme}://{host}{base_path.rstrip('/')}/{quoted_key}"
