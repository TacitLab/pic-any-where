# 厂商适配参考

所有下列厂商均兼容 AWS Signature V4 + S3 API，pic-any-where 用同一套签名与之通信。
配置时只需选择厂商并填写 region 和 bucket，endpoint 由预设模板自动推导；
任何 profile 都可用 `endpoint` / `addressing_style` 字段覆盖默认值。

## AWS S3（provider: `aws`）

- endpoint：`s3.{region}.amazonaws.com`，virtual-host 寻址
- 签名 region 即桶所在 region，如 `us-east-1`、`ap-southeast-1`
- 凭证可直接复用 `~/.aws/credentials`（默认 `[default]` 段，profile 里可用
  `aws_profile` 指定其他段），无需重复配置

## 腾讯云 COS（provider: `tencent`）

- endpoint：`cos.{region}.myqcloud.com`，virtual-host 寻址
- bucket 必须带 APPID 后缀：`mybucket-1250000000`（APPID 在控制台"账号信息"查看）
- 常用 region：`ap-guangzhou`、`ap-shanghai`、`ap-beijing`、`ap-chengdu`、`ap-singapore`
- 建议使用 CAM 子用户密钥，仅授权单个桶的最小权限

## 阿里云 OSS（provider: `aliyun`）

- OSS 官方兼容 S3 协议（
  [官方文档](https://help.aliyun.com/zh/oss/developer-reference/use-aws-sdks-to-access-oss)），
  endpoint 直接用 OSS 地址：`oss-{region}.aliyuncs.com`，virtual-host 寻址
- 常用 region：`cn-hangzhou`、`cn-shanghai`、`cn-beijing`、`cn-shenzhen`
- 注意 OSS 的 ACL 只有"私有 / 公共读 / 公共读写"三档，图床用"公共读"即可

## Cloudflare R2（provider: `cloudflare`）

- endpoint：`{account_id}.r2.cloudflarestorage.com`，region 固定 `auto`
- 需要额外填写 `account_id`（Cloudflare 仪表盘右侧可复制）
- 公开访问建议绑定自定义域（R2 Custom Domain），配成 `public_base_url`

## 七牛云 Kodo（provider: `qiniu`）

- endpoint：`s3.{region}.qiniucs.com`，region 形如 `cn-east-1`
- 需在 Kodo 控制台确认 bucket 已启用 S3 兼容域名

## 自定义 / MinIO（provider: `custom`）

- 必须显式填写 `endpoint`（不含 scheme）
- 默认 path 风格寻址（`endpoint/bucket/key`），MinIO、Ceph 等一般如此；
  支持 virtual-host 的服务可设 `addressing_style: "virtual"`
- 本地无 TLS 的 MinIO 可设 `insecure_http: true`（仅限测试环境）

## public_base_url（自定义源站域名 / CDN）

profile 里配置 `public_base_url` 后，上传返回的链接一律走该域名：

```
public_base_url = https://img.example.com
返回：https://img.example.com/i/2024/01/<hash>.png
```

要求：
- 必须是 `https://`
- 域名需已 CNAME/回源到对应 bucket（各厂商控制台均有"自定义域名/CDN 加速"入口）
- 未配置时回退为厂商默认域名（此时链接能否公开访问取决于桶的读权限）
