---
name: pic-any-where
description: "把 S3 兼容对象存储（AWS S3、腾讯云 COS、阿里云 OSS、Cloudflare R2、七牛 Kodo、MinIO 等）当作个人图床使用：上传本地图片并返回可访问链接（优先自定义域名/CDN），支持 URL、Markdown、HTML 输出格式。当用户要求「上传图片到图床」「生成图片链接」「image hosting / image bed / 图床」「上传到 S3 / OSS / COS 并拿链接」时使用本技能。"
---

# pic-any-where —— S3 对象存储图床

将用户本地图片上传到其自有的 S3 兼容对象存储桶，输出访问链接。
零第三方依赖，仅需 Python 3.8+。凭证存系统钥匙串，永不进入对话与日志。

## 安全红线（必须遵守）

- **绝不要**让用户在对话中粘贴 AccessKey / SecretKey。凭证配置一律引导用户
  自己在终端运行 `config init` 或 `config set-credential`（交互式、输入不回显）。
- 不要把任何凭证内容写进文件、日志、issue 或回复中。
- 不要修改 `~/.config/pic-any-where/`（Windows 为 `%APPDATA%\pic-any-where\`）
  下的配置文件；配置变更通过 `paw.py config` 子命令完成。
- 删除对象（`rm`）前先向用户确认 key。

## 工作流

### 1. 检查是否已配置

```bash
python3 scripts/paw.py doctor
```

- 全部通过 → 直接进入第 3 步上传。
- 提示"尚未配置"或凭证缺失 → 进入第 2 步。

### 2. 首次配置（需要用户本人在终端操作）

让用户运行交互向导（选厂商 → region → bucket → 自定义域名 → 凭证入钥匙串）：

```bash
python3 scripts/paw.py config init
```

若用户已有环境变量或 `~/.aws/credentials`，doctor 会直接识别，可跳过向导。
各厂商的 endpoint/region/注意事项见 [references/providers.md](references/providers.md)；
最小权限策略与安全建议见 [references/security.md](references/security.md)。

### 3. 上传图片

```bash
python3 scripts/paw.py upload /path/to/pic.png                # 输出 URL
python3 scripts/paw.py upload a.png b.jpg --format markdown   # Markdown 格式
python3 scripts/paw.py upload pic.png --copy                  # 复制到剪贴板
```

- 上传成功只输出链接，逐文件一行；把链接原样交给用户。
- 对象 key 自动按内容哈希命名（`i/YYYY/MM/<hash>.<ext>`），同图去重；
  用户指定名称时用 `--key`（仅单文件）。

### 4. 其他常用命令

```bash
python3 scripts/paw.py url i/2024/01/abcdef.png            # 由 key 生成链接
python3 scripts/paw.py url <key> --presign 3600            # 私有桶临时链接（1 小时有效）
python3 scripts/paw.py ls --prefix i/2024/                 # 列出对象
python3 scripts/paw.py rm <key>                            # 删除（先确认）
```

多 bucket/多厂商场景用 `--profile <名称>` 切换（全局参数，放子命令前后均可）。

### 5. 更新本技能

```bash
python3 scripts/paw.py self-update
```

从其 git 安装来源拉取最新提交（fast-forward only）。安装目录存在未提交的
本地改动时会拒绝执行并列出改动文件，此时不要擅自提交或还原，先把情况告诉用户。
若目录不是 git 工作副本（如下载解压安装），提示用户改用 git clone 重新安装。

## 故障排查

| 现象 | 处理 |
|---|---|
| `未找到可用凭证` | 让用户跑 `config set-credential`，或检查环境变量 |
| `SignatureDoesNotMatch` / 403 | 多为 region 或 bucket 名错误（COS 需带 APPID 后缀），跑 `doctor` 复核 |
| `NoSuchBucket` / 网络错误 | 检查 endpoint 推导是否正确；自定义服务确认寻址风格（MinIO 用 path） |
| 链接能上传但打不开 | 桶非公开读：改用 `--presign` 临时链接，或配置 CDN/自定义域名并设公开读 |
| 上传被拒绝且提示格式 | 文件不是有效图片（扩展名+魔数双重校验），确认文件内容 |

排查时均可先跑 `python3 scripts/paw.py doctor --write` 做完整自检。
