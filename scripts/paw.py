#!/usr/bin/env python3
"""paw — pic-any-where 命令行入口：把 S3 兼容对象存储当作个人图床。

用法见各子命令 --help。凭证从不通过命令行参数传入。
"""

import argparse
import getpass
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pawlib import config as cfg
from pawlib import credstore
from pawlib import providers
from pawlib import s3client
from pawlib import selfupdate
from pawlib import ui
from pawlib import uploader


def _err(msg):
    ui.fail(msg)


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}B"


def _load_profile(args):
    data = cfg.load_config()
    return cfg.get_profile(data, getattr(args, "profile", None))


def _make_client(profile):
    creds = credstore.resolve_credentials(profile)
    return s3client.S3Client(profile, creds), creds


def _copy_to_clipboard(text):
    candidates = []
    if sys.platform == "darwin":
        candidates = [["pbcopy"]]
    elif sys.platform == "win32":
        candidates = [["clip"]]
    else:
        candidates = [["wl-copy"], ["xclip", "-selection", "clipboard"],
                      ["xsel", "--clipboard", "--input"]]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True,
                               capture_output=True, check=True)
                return True
            except subprocess.CalledProcessError:
                continue
    return False


# ------------------------------------------------------------------ config

def cmd_config_init(args):
    ui.header("pic-any-where 初始化向导（Ctrl-C 取消）", stream=sys.stdout)
    print()

    names = sorted(providers.PROVIDERS)
    for i, name in enumerate(names, 1):
        p = providers.PROVIDERS[name]
        print(f"  {ui.paint('36', str(i), sys.stdout)}. {p['display']}（{name}）")
    while True:
        choice = input("选择厂商 [序号或名称]: ").strip()
        if choice in names:
            provider = choice
            break
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            provider = names[int(choice) - 1]
            break
        ui.warn("无效输入，请重试")
    preset = providers.PROVIDERS[provider]
    ui.info(preset["hint"])

    region_default = preset["default_region"]
    if preset["common_regions"]:
        print("常用 region：" + ", ".join(preset["common_regions"]))
    region = input(f"region [{region_default}]: ").strip() or region_default

    account_id = None
    if preset["needs_account_id"]:
        account_id = input("Cloudflare Account ID: ").strip()

    endpoint = None
    addressing = None
    if provider == "custom":
        endpoint = input("endpoint（如 minio.example.com:9000，不含 scheme）: ").strip()
        addressing = input("寻址风格 virtual/path [path]: ").strip() or "path"

    bucket = input("bucket 名称: ").strip()
    if not bucket:
        _err("bucket 不能为空")
        return 1

    public_base = input("自定义访问域名（CDN/源站，如 https://img.example.com，可留空）: ").strip()
    if public_base and not public_base.startswith("https://"):
        _err("自定义域名必须使用 https://，请检查")
        return 1

    prefix = input("对象 key 前缀 [i/]: ").strip() or "i/"

    profile = {
        "provider": provider,
        "region": region,
        "bucket": bucket,
        "account_id": account_id,
        "endpoint": endpoint,
        "addressing_style": addressing,
        "public_base_url": public_base or None,
        "key_prefix": prefix,
    }

    data = cfg.load_config()
    name = input("profile 名称 [default]: ").strip() or "default"
    cfg.set_profile(data, name, profile)
    path = cfg.save_config(data)
    print()
    ui.ok(f"配置已保存：{path}", stream=sys.stdout)

    # 凭证写入钥匙串
    ui.info("接下来配置凭证（将写入系统钥匙串，不会显示也不会落盘明文）", stream=sys.stdout)
    if input("现在配置凭证？[Y/n]: ").strip().lower() not in ("n", "no"):
        return _interactive_set_credential(name)
    print(f"可稍后运行：{os.path.basename(__file__)} config set-credential --profile {name}")
    return 0


def _interactive_set_credential(profile_name):
    backend = credstore.get_backend()
    if backend is None:
        _err("未检测到可用的系统钥匙串后端。请改用环境变量方式：\n"
             "  export PAW_ACCESS_KEY_ID=...\n"
             "  export PAW_SECRET_ACCESS_KEY=...")
        return 1
    access_key = input("AccessKey ID: ").strip()
    secret_key = getpass.getpass("AccessKey Secret（输入不显示）: ").strip()
    token = getpass.getpass("Session Token（临时凭证才需要，可留空）: ").strip() or None
    if not access_key or not secret_key:
        _err("AccessKey ID / Secret 不能为空")
        return 1
    backend_name = credstore.store_credentials(
        profile_name, access_key, secret_key, token)
    ui.ok(f"凭证已写入 {backend_name}（条目：{credstore.SERVICE_NAME}/{profile_name}）", stream=sys.stdout)
    return 0


def cmd_config_set(args):
    """非交互式配置：供对话/脚本场景使用，只更新显式提供的字段，其余保留。"""
    data = cfg.load_config()
    name = args.name or "default"
    existing = data.get("profiles", {}).get(name, {})

    updates = {k: v for k, v in {
        "provider": args.provider,
        "region": args.region,
        "bucket": args.bucket,
        "account_id": args.account_id,
        "endpoint": args.endpoint,
        "addressing_style": args.addressing_style,
        "public_base_url": args.public_base_url,
        "key_prefix": args.key_prefix,
        "object_acl": args.object_acl,
    }.items() if v is not None}

    profile = dict(existing)
    profile.update(updates)
    if not profile.get("bucket"):
        _err("bucket 不能为空（新建 profile 必须提供 --bucket）")
        return 1
    if not profile.get("provider"):
        _err("provider 不能为空（可选：aws/tencent/aliyun/cloudflare/qiniu/custom）")
        return 1

    cfg.set_profile(data, name, profile)
    path = cfg.save_config(data)
    ui.ok(f"配置已保存：{path}（profile={name}）", stream=sys.stdout)
    ui.dim(f"云端连通性可运行 {os.path.basename(__file__)} doctor --profile {name} 验证", stream=sys.stdout)
    return 0


def cmd_config_set_credential(args):
    data = cfg.load_config()
    profile = cfg.get_profile(data, args.profile)
    return _interactive_set_credential(profile["_name"])


def cmd_config_show(args):
    data = cfg.load_config()
    path = cfg.config_path()
    if not data["profiles"]:
        ui.dim(f"尚无配置（{path}），请先运行 config init", stream=sys.stdout)
        return 0
    ui.dim(f"配置文件：{path}", stream=sys.stdout)
    ui.dim(f"默认 profile：{data.get('default_profile')}", stream=sys.stdout)
    for name, p in sorted(data["profiles"].items()):
        print()
        print(ui.paint("1", f"[{name}]", sys.stdout))
        for key in cfg.PROFILE_FIELDS:
            if key in p and p[key] is not None:
                print(f"  {ui.paint('36', key, sys.stdout)} = {p[key]}")
        try:
            creds = credstore.resolve_credentials(dict(p, _name=name))
            print(f"  凭证来源 = {creds.source}（{credstore.redact(creds.access_key)}）")
        except credstore.CredentialError:
            print(f"  凭证来源 = {ui.paint('33', '未配置', sys.stdout)}")
    for w in cfg.check_config_permissions():
        ui.warn(w)
    return 0


# ------------------------------------------------------------------ doctor

def cmd_doctor(args):
    ok = True

    def check(label, passed, detail=""):
        nonlocal ok
        text = label + (f" — {detail}" if detail else "")
        if passed:
            ui.ok(text, stream=sys.stdout)
        else:
            ui.fail(text, stream=sys.stdout)
        if not passed:
            ok = False

    ui.header("pic-any-where 自检", stream=sys.stdout)
    print()

    try:
        profile = _load_profile(args)
        check("配置加载", True, f"profile={profile['_name']} bucket={profile.get('bucket')}")
    except cfg.ConfigError as e:
        check("配置加载", False, str(e))
        return 1

    backend = credstore.get_backend()
    check("钥匙串后端", backend is not None,
          backend.name if backend else "不可用，仅环境变量方式可用")

    try:
        creds = credstore.resolve_credentials(profile)
        check("凭证解析", True, f"{creds.source}（{credstore.redact(creds.access_key)}）"
              + ("，含临时 token" if creds.session_token else ""))
    except credstore.CredentialError as e:
        check("凭证解析", False, str(e))
        return 1

    if profile.get("insecure_http"):
        ui.warn("传输加密 — 已允许 HTTP（仅建议本地测试环境）", stream=sys.stdout)
    else:
        check("传输加密", True, "HTTPS")

    if profile.get("public_base_url"):
        check("自定义域名", profile["public_base_url"].startswith("https://"),
              profile["public_base_url"])

    try:
        client, _ = _make_client(profile)
        client.head_bucket()
        check("云端连通（HEAD Bucket）", True, f"{client.host}")
    except Exception as e:
        check("云端连通（HEAD Bucket）", False, str(e))
        return 1

    if args.write:
        probe = f"{profile.get('key_prefix', 'i/').rstrip('/')}/.paw-doctor-probe"
        try:
            client.put_object(probe, b"paw", "text/plain")
            client.delete_object(probe)
            check("写权限探测（PUT+DELETE）", True)
        except Exception as e:
            check("写权限探测（PUT+DELETE）", False, str(e))

    print()
    if ok:
        ui.ok("结果：全部通过", stream=sys.stdout)
    else:
        ui.fail("结果：存在失败项，请按提示修复", stream=sys.stdout)
    return 0 if ok else 1


# ------------------------------------------------------------------ 上传等

def cmd_upload(args):
    profile = _load_profile(args)
    client, _ = _make_client(profile)
    if args.key and len(args.files) > 1:
        _err("--key 只能用于单文件上传")
        return 1
    rc = 0
    outputs = []
    total = len(args.files)
    for i, path in enumerate(args.files, 1):
        try:
            size = os.path.getsize(path) if os.path.isfile(path) else 0
            ui.info(f"[{i}/{total}] 上传中 {path}（{_fmt_size(size)}）…")
            key, url = uploader.upload_file(client, profile, path, key=args.key,
                                       prefix=args.prefix, public=args.public)
            alt = os.path.splitext(os.path.basename(path))[0]
            outputs.append(uploader.format_output(url, args.format, alt))
            ui.ok(f"{path} → {key}")
            if not profile.get("public_base_url"):
                ui.warn("未配置自定义域名，URL 指向存储默认域名；私有桶可用 url 子命令 --presign 生成临时链接")
        except (uploader.UploadError, s3client.S3Error) as e:
            ui.fail(f"{path}: {e}")
            rc = 1
    for line in outputs:
        ui.url_out(line)
    if total > 1 or rc:
        ui.info(f"完成：{len(outputs)}/{total} 个文件上传成功")
    if args.copy and outputs:
        text = "\n".join(outputs)
        if _copy_to_clipboard(text):
            ui.dim("已复制到剪贴板")
        else:
            ui.warn("未找到可用的剪贴板工具，跳过复制")
    return rc


def cmd_url(args):
    profile = _load_profile(args)
    key = uploader.sanitize_key(args.key)
    if args.presign:
        client, _ = _make_client(profile)
        ui.url_out(client.presign_get(key, expires=args.presign))
    else:
        ui.url_out(uploader.public_url(profile, key))
    return 0


def cmd_ls(args):
    profile = _load_profile(args)
    client, _ = _make_client(profile)
    items = client.list_objects(prefix=args.prefix or "", max_keys=args.max_keys)
    if not items:
        ui.dim("（没有对象）", stream=sys.stdout)
        return 0
    for item in items:
        size = ui.paint("2", f"{item['size']:>12}", sys.stdout)
        key = ui.paint("36", item["key"], sys.stdout)
        print(f"{size}  {item['last_modified']}  {key}")
    ui.dim(f"共 {len(items)} 个对象", stream=sys.stdout)
    return 0


def cmd_rm(args):
    profile = _load_profile(args)
    client, _ = _make_client(profile)
    key = uploader.sanitize_key(args.key)
    client.delete_object(key)
    ui.ok(f"已删除：{key}", stream=sys.stdout)
    return 0


def cmd_self_update(args):
    updated, summary = selfupdate.self_update()
    (ui.ok if updated else ui.dim)(summary, stream=sys.stdout)
    return 0


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="paw",
        description="pic-any-where：把 S3 兼容对象存储当作个人图床")
    parser.add_argument("--profile", help="使用指定 profile（默认取配置中的 default_profile）")
    # 让 --profile 在子命令后也可用（SUPPRESS 避免覆盖顶层解析值）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("config", help="配置管理", parents=[common])
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("init", help="交互式初始化向导")
    config_sub.add_parser("show", help="显示当前配置（凭证脱敏）")
    config_sub.add_parser("set-credential", help="将 AK/SK 写入系统钥匙串")
    p_set = config_sub.add_parser("set", help="非交互式写入/更新 profile 配置（适合对话/脚本场景）")
    p_set.add_argument("--name", help="profile 名称，缺省 default")
    p_set.add_argument("--provider", choices=sorted(providers.PROVIDERS),
                     help="厂商：aws/tencent/aliyun/cloudflare/qiniu/custom")
    p_set.add_argument("--region", help="region，如 ap-guangzhou")
    p_set.add_argument("--bucket", help="bucket 名称（COS 需带 APPID 后缀）")
    p_set.add_argument("--account-id", help="Cloudflare R2 的 account_id")
    p_set.add_argument("--endpoint", help="自定义 endpoint（custom 厂商必填）")
    p_set.add_argument("--addressing-style", choices=["virtual", "path"], help="寻址风格")
    p_set.add_argument("--public-base-url", help="自定义访问域名/CDN，如 https://img.example.com")
    p_set.add_argument("--key-prefix", help="对象 key 前缀（上传目录），如 i/ 或 blog/")
    p_set.add_argument("--object-acl", choices=["private", "public-read"],
                     help="上传时默认的对象 ACL，图床一般配 public-read")

    p_doctor = sub.add_parser("doctor", help="自检：配置 / 凭证 / 连通性",
                              parents=[common])
    p_doctor.add_argument("--write", action="store_true",
                          help="额外做写权限探测（上传并删除一个小对象）")

    p_upload = sub.add_parser("upload", help="上传图片并输出访问链接",
                              parents=[common])
    p_upload.add_argument("files", nargs="+", help="图片文件路径")
    p_upload.add_argument("--key", help="自定义对象 key（仅单文件）")
    p_upload.add_argument("--prefix", help="上传到桶内指定目录（覆盖 profile 的 key_prefix）")
    p_upload.add_argument("--public", action="store_true",
                          help="本次上传的对象设为公有读（x-amz-acl: public-read）")
    p_upload.add_argument("--format", choices=["url", "markdown", "html"],
                          default="url", help="输出格式")
    p_upload.add_argument("--copy", action="store_true", help="复制结果到剪贴板")

    p_url = sub.add_parser("url", help="由对象 key 生成访问链接", parents=[common])
    p_url.add_argument("key")
    p_url.add_argument("--presign", type=int, metavar="SECONDS",
                       help="生成带签名的临时链接（私有桶用），参数为有效期秒数")

    p_ls = sub.add_parser("ls", help="列出桶内对象", parents=[common])
    p_ls.add_argument("--prefix", help="按 key 前缀过滤")
    p_ls.add_argument("--max-keys", type=int, default=100)

    p_rm = sub.add_parser("rm", help="删除对象", parents=[common])
    p_rm.add_argument("key")

    sub.add_parser("self-update", help="从 git 仓库拉取最新提交更新本工具")
    return parser


def main(argv=None):
    ui.enable_windows_ansi()
    args = build_parser().parse_args(argv)
    handlers = {
        ("config", "init"): cmd_config_init,
        ("config", "show"): cmd_config_show,
        ("config", "set"): cmd_config_set,
        ("config", "set-credential"): cmd_config_set_credential,
    }
    if args.command == "config":
        handler = handlers[(args.command, args.config_command)]
    else:
        handler = {"doctor": cmd_doctor, "upload": cmd_upload,
                   "url": cmd_url, "ls": cmd_ls, "rm": cmd_rm,
                   "self-update": cmd_self_update}[args.command]
    try:
        return handler(args)
    except (cfg.ConfigError, credstore.CredentialError,
            providers.ProviderError, selfupdate.UpdateError) as e:
        _err(str(e))
        return 1
    except KeyboardInterrupt:
        ui.dim("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
