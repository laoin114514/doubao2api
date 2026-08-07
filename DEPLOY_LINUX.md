# doubao2api Linux（Docker）部署指南

在 Ubuntu/Debian 服务器上用 Docker 跑豆包代理服务。全程无需服务器显示器——
浏览器跑在容器内的 xvfb 虚拟显示里，登录用扫码（二维码下载到本地手机扫）。

> ⚠️ 重要提醒
> - **headless 模式会被豆包风控**：本方案用 xvfb 虚拟显示保持「有头」浏览器指纹。
> - **机房 IP 风控风险**：阿里云/腾讯云等机房 IP 触发验证码概率高于家用宽带。
>   若频繁验证码，请降低请求频率或考虑在自家电脑（家用 IP）上跑。
> - **必须设置 API Key**：服务暴露在公网时，不设密钥任何人都能白嫖你的豆包账号。

---

## 1. 前置要求

- Ubuntu 20.04+ / Debian 11+（64 位）
- Docker 20.10+ 与 docker compose 插件
- 一个豆包账号（手机号 / 抖音 / 飞书）
- 服务器能访问 `doubao.com`（国内服务器最佳；海外服务器访问可能慢或被限）

检查：
```bash
docker --version
docker compose version
```

## 2. 把项目放到服务器

方式 A：直接拷（从你 Windows 机器上已有的 clone）
```bash
# 在 Windows 机器上执行
scp -r C:/Users/29084/Desktop/code/zcodeWorkspace/doubao2api user@服务器IP:/opt/
```

方式 B：服务器上重新 clone（需要 GitHub 访问）
```bash
git clone --depth 1 https://github.com/wangchuxiaoji-oss/doubao2api.git
cd doubao2api
```

## 3. 配置并启动

```bash
cd doubao2api

# 3.1 生成 API 密钥并写入 compose
API_KEY=$(openssl rand -hex 32)
echo "你的 API Key: $API_KEY"   # 记下来，agent 配置要用
sed -i "s/DOUBAO_API_KEY: \".*\"/DOUBAO_API_KEY: \"$API_KEY\"/" docker-compose.yml

# 3.2 首次构建（含 chromium 下载，约 3~5 分钟，需外网）
docker compose up -d --build

# 3.3 看启动日志（出现 "Ready! ... fetch_hook=True" 即就绪）
docker compose logs -f doubao2api
```

## 4. 扫码登录（首次必做）

登录态存在容器卷 `./profile` 里，**只需做一次**，之后重启容器不掉。

```bash
# 4.1 生成二维码并保存到本地图片文件
curl -s -X POST http://服务器IP:9090/v1/session/qr-login \
  -H "Authorization: Bearer $API_KEY" \
  | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('qr.png','wb').write(base64.b64decode(d['qr_image_base64']))"

# 4.2 把 qr.png 下载到手机/本地电脑，用「豆包 App → 扫一扫」扫码
#     （Windows 本机也可以：把 qr.png scp 回来打开）

# 4.3 轮询登录状态，直到出现 success
curl -s http://服务器IP:9090/v1/session/qr-login -H "Authorization: Bearer $API_KEY"
# 期望: {"status":"success", ...}
```

扫码成功后服务自动注入登录态并刷新浏览器，之后即可正常使用。

## 5. 验证

```bash
# 健康检查
curl -s http://服务器IP:9090/health -H "Authorization: Bearer $API_KEY"
# 期望: {"status":"ok","logged_in":true,...}

# 发一条消息
curl -s http://服务器IP:9090/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"doubao","messages":[{"role":"user","content":"你好，回复"收到"即可"}]}'
```

## 6. 接入 agent

```text
base_url = http://服务器IP:9090/v1
api_key  = <第 3 步生成的 API_KEY>
model    = doubao        # 可选 doubao-think / doubao-pro / doubao-expert
```

- **OpenAI 兼容客户端**（Cline/Continue/Cherry Studio/NextChat 等）：直接填上面三项。
- **ZCode / Claude Code**（走 Anthropic 协议）：需要一个转换桥接，见下文「ZCode 接入」。

## 7. 日常维护

| 操作 | 命令 |
|---|---|
| 看日志 | `docker compose logs -f doubao2api` |
| 重启 | `docker compose restart doubao2api` |
| 停止 | `docker compose down` |
| 重新登录 | 删掉 `./profile` 后重启容器，再走第 4 步 |

**遇到验证码（接口返回 710022004）**：
1. 降低请求频率（agent 侧间隔 ≥5 秒/次）；
2. 若持续验证码，删掉 `./profile` 重新扫码登录，让账号"翻篇"；
3. 频率过高持续风控 → 换家用网络跑（本机 Windows 方案）。

## 9. 构建太慢？排查与加速

**症状**：`docker compose up -d --build` 卡在 `apt-get update` / `pip install` / 下载 chromium 很久（可达 10~20 分钟）。

**原因**：服务器在国内访问国外源（deb.debian.org / pypi.org / Microsoft CDN）慢。

**方案**：Dockerfile.linux 已默认内置国内镜像源（阿里云 apt + 清华 pip + npmmirror 浏览器）。
按服务器厂商在 `.env` 里覆盖 `APT_MIRROR` 选最快的：

| 服务器厂商 | APT_MIRROR 建议值 |
|---|---|
| 阿里云 ECS | `mirrors.aliyun.com`（默认） |
| 腾讯云 CVM | `mirrors.tencentyun.com`（内网，最快） |
| 华为云 | `mirrors.huaweicloud.com` |
| 通用/清华 | `mirrors.tuna.tsinghua.edu.cn` |

```bash
# 示例：腾讯云服务器
cat >> .env <<'EOF'
APT_MIRROR=mirrors.tencentyun.com
EOF
docker compose build --progress=plain   # 重新构建
```

**预期耗时**：镜像源正确时，apt 层 ~1 分钟、chromium 下载 ~1~2 分钟，总构建 3~5 分钟。

**仍然很慢 / 服务器网络极差**：改在本地（Windows）构建镜像推到私有仓库，服务器只 pull：
```bash
# 本地构建并推送（国内可用阿里云 ACR 个人版，免费）
docker build -f Dockerfile.linux -t registry.cn-hangzhou.aliyuncs.com/你的命名空间/doubao2api:latest .
docker push registry.cn-hangzhou.aliyuncs.com/你的命名空间/doubao2api:latest

# 服务器上改 compose 的 image 指向该镜像并 pull
docker compose pull && docker compose up -d
```

## 10. 端口与防火墙

- 服务监听 `9090`；安全组/防火墙放行 `9090`（或只对你自己 IP 开放）。
- 用 SSH 隧道可以不开公网端口：
  ```bash
  # 本地执行，把服务器 9090 映射到本地 9090
  ssh -L 9090:127.0.0.1:9090 user@服务器IP
  # 然后 agent 直接指向 http://127.0.0.1:9090/v1
  ```
