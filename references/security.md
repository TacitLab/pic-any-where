# 安全模型与加固建议

## 凭证如何被保护

1. **存储**：AK/SK 只写入操作系统钥匙串——macOS Keychain、Linux libsecret
  （secret-tool）、Windows 凭据管理器。配置文件中默认不保存任何密钥。
2. **录入**：凭证通过交互式终端录入（`getpass`，不回显），绝不接受命令行参数
  传入（避免 shell history / 进程列表泄露），也绝不应出现在与 AI 的对话中。
3. **使用**：脚本运行时从钥匙串读取，仅驻留内存；所有输出、错误信息中对
   AccessKey 做脱敏（只显示前 4 位），HTTP 错误响应不回显签名材料。
4. **降级**：无钥匙串环境可用环境变量（`PAW_ACCESS_KEY_ID` 等，支持
   `PAW_SESSION_TOKEN` 临时凭证）；配置文件内嵌密钥默认被拒绝，需显式
   `allow_file_credentials: true` 且文件权限会被检查（应为 0600）。

### 已知限制

- macOS 的 `security add-generic-password -w` 在进程存续的极短瞬间，密钥对
  同机其他进程可见（`ps`）。这是 security CLI 的固有限制；录入时避免在
  共享/受监控机器上操作。
- 环境变量方式下，凭证对同一用户的子进程可见，适合临时凭证而非长期密钥。

## 强烈建议：最小权限子账号

不要为图床使用主账号密钥。各厂商均支持创建仅授权单个桶的子账号：

- **腾讯云 CAM**：子用户绑定策略，资源限定 `qcs::cos:{region}:uid/{uin}:{bucket}/*`，
  动作仅 `cos:PutObject`、`cos:GetObject`、`cos:DeleteObject`、`cos:HeadBucket`、`cos:GetBucket`（List）
- **阿里云 RAM**：自定义策略，`Resource` 限定 `acs:oss:*:*:{bucket}/*`，
  Action 仅 `oss:PutObject`、`oss:GetObject`、`oss:DeleteObject`、`oss:ListObjects`
- **AWS IAM**：策略 `Resource` 限定 `arn:aws:s3:::{bucket}/*`，
  Action 仅 `s3:PutObject`、`s3:GetObject`、`s3:DeleteObject`、`s3:ListBucket`

这样即使密钥泄露，影响也被限制在这一个图床桶内。

## 更进一步的选项（按需）

- **STS 临时凭证**：本工具全链路支持 session token。可以把长期密钥放在
  受控的地方，本地只放短期临时凭证（环境变量传入），泄露窗口从"永久"
  缩短到小时级。
- **桶策略**：图床桶设"公共读、禁止公共写"；开启防盗链（Referer 白名单）
  可减少流量盗刷；删除类操作可只保留给受信网络。
- **传输与内容**：全链路强制 HTTPS（`insecure_http` 仅限本地 MinIO 测试）；
  上传做扩展名 + 魔数双重校验，防止把可执行文件伪装成图片。
