# pic-any-where

把 S3 兼容对象存储变成你的个人图床。一个符合 Anthropic Agent Skills 规范的
技能包，也可以当作独立 CLI 使用。

- **多云适配**：AWS S3、腾讯云 COS、阿里云 OSS、Cloudflare R2、七牛 Kodo、
  MinIO 及任意 S3 兼容服务——选厂商填 region/bucket 即可，endpoint 自动推导
- **凭证安全**：AK/SK 存系统钥匙串（macOS Keychain / libsecret / Windows 凭据
  管理器），不落明文、不进对话；支持 STS 临时凭证
- **自定义域名**：配置 CDN/源站域名后，上传即返回你的域名链接
- **零依赖**：纯 Python 3.8+ 标准库，无需 pip install

## 安装为 Agent Skill

把本仓库目录放入 skills 目录（如 `~/.claude/skills/` 或项目的 `.agents/skills/`），
Agent 会在你需要"上传图片到图床"时自动使用 `SKILL.md`。

## 快速开始（CLI）

```bash
# 1. 初始化（选厂商 → region → bucket → 自定义域名 → 凭证入钥匙串）
python3 scripts/paw.py config init

# 2. 自检（配置 / 钥匙串 / 凭证 / 云端连通性）
python3 scripts/paw.py doctor --write

# 3. 上传
python3 scripts/paw.py upload ~/Desktop/pic.png
# https://img.example.com/i/2024/01/9f2c….png

python3 scripts/paw.py upload a.png b.jpg --format markdown --copy
```

## 命令一览

| 命令 | 说明 |
|---|---|
| `config init` | 交互式初始化向导 |
| `config show` | 查看配置（凭证脱敏） |
| `config set-credential` | 写入/更新钥匙串凭证 |
| `doctor [--write]` | 自检，含云端连通与写权限探测 |
| `upload <file...> [--key K] [--format url\|markdown\|html] [--copy]` | 上传图片 |
| `url <key> [--presign 秒]` | 生成访问链接 / 私有桶临时链接 |
| `ls [--prefix P]` | 列出对象 |
| `rm <key>` | 删除对象 |

全局参数 `--profile <名称>` 用于多 bucket / 多厂商切换。

## 凭证来源（按优先级）

1. 环境变量 `PAW_ACCESS_KEY_ID` / `PAW_SECRET_ACCESS_KEY`（或 `AWS_*`，
   临时凭证加 `*_SESSION_TOKEN`）
2. 系统钥匙串（推荐，`config set-credential` 写入）
3. `~/.aws/credentials`
4. 配置文件内嵌（默认拒绝，详见 [references/security.md](references/security.md)）

## 目录结构

```
SKILL.md            # Agent Skill 入口
scripts/paw.py      # CLI 主入口
scripts/pawlib/     # 核心库（sigv4 / providers / config / credstore / s3client / uploader）
references/         # 厂商适配与安全参考
tests/              # 单元测试（stdlib unittest）
```

## 测试

```bash
python3 -m unittest discover -s tests
```

签名实现以 AWS 官方 SigV4 测试向量验证。
