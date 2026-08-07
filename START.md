# doubao2api 启动流程

豆包网页版 → OpenAI 兼容代理的完整启动/维护手册。
服务运行在 **Windows 本机**（有头 Chrome + 复用登录态 profile）。

---

## 0. 先查状态（最快确认要不要启动）

```bash
curl http://127.0.0.1:9090/health
```

| 返回 | 含义 | 怎么办 |
|---|---|---|
| `{"status":"ok","logged_in":true,...}` | **服务已运行且已登录** | 直接用，什么都不用做 |
| `{"status":"ok","logged_in":false,...}` | 服务已运行但登录态失效 | 走 **§4.2 重新登录** |
| `{"status":"not_ready"...}` 或无响应 | 服务没在跑 | 走 **§1 日常启动** |

---

## 1. 日常启动（服务没在跑时）

```bash
cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao2api
bash ./start.sh
```

start.sh 会自动处理两种情况：
- **端口 9090 已被占用** → 提示"服务已在运行"并显示健康状态，直接退出（不用管）
- **正常启动** → 打印 `Listening on http://0.0.0.0:9090`，同时**弹出一个豆包浏览器窗口**（这是服务的会话载体，别关）

启动完成后验证：
```bash
curl http://127.0.0.1:9090/health
# 期望 {"status":"ok","logged_in":true,...}
```

> 依赖说明：本机已装好（Python 3.11 + playwright + playwright-stealth + chromium 已下载）。
> 只有换新机器才需要重新装，见 §2。

---

## 2. 首次部署（换新机器 / 全新环境）

### 2.1 安装依赖
```bash
cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao2api
pip install -r requirements.txt
pip install playwright-stealth
python -m playwright install chromium        # 下载浏览器二进制（约 150MB）
```

### 2.2 登录豆包（首次必做，登录态存 doubao-proxy/profile）
```bash
cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao-proxy
python main.py login
```
弹出 Chrome 窗口，手机号 / 抖音扫码 / 飞书任选，登录完成后自动检测并保存。

### 2.3 启动服务
```bash
cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao2api
bash ./start.sh
```

### 2.4 验证
```bash
curl http://127.0.0.1:9090/health          # 期望 logged_in:true
curl http://127.0.0.1:9090/v1/models       # 期望模型列表
```

---

## 3. 停止服务

```bash
# 找到占用 9090 的进程
netstat -ano | grep ":9090" | grep LISTENING    # 最后一列是 PID
taskkill //PID <PID> //F
```
或直接关掉那个 python 进程 / 任务管理器结束。
> 有头 Chrome 窗口会随服务一起退出，下次 start.sh 会自动重启一个新的。

---

## 4. 排障

### 4.1 启动报错 `TargetClosedError` / Chromium 秒退
**原因**：服务其实已在运行，9090 端口和 profile 目录被占，新实例抢不到资源。
**解决**：不用管，`curl http://127.0.0.1:9090/health` 确认旧服务健康即可；或先按 §3 停掉再启动。

### 4.2 登录态失效（health 显示 logged_in:false）
```bash
cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao-proxy
python main.py login        # 重新登录一次
# 然后重启 doubao2api 服务（§3 停 → §1 起）
```

### 4.3 验证码风控（接口返回 710022004 / health 里 needs_captcha:true）
1. **先降频**：agent 请求间隔 ≥5 秒/次，连发容易触发
2. **解除验证**：
   ```bash
   cd C:/Users/29084/Desktop/code/zcodeWorkspace/doubao2api
   python captcha_fix.py
   # 浏览器弹出后手动通过验证码，窗口保持 60 秒后自动关
   ```
3. **重启服务**让风控状态刷新（§3 停 → §1 起）
4. 还不行 → 按 §4.2 重新登录让账号"翻篇"

### 4.4 请求报 503（未登录/浏览器未就绪/需验证码）
```bash
curl -s -X POST http://127.0.0.1:9090/auth/reset_captcha   # 清验证码标记
curl http://127.0.0.1:9090/health                          # 再查状态
```
若 logged_in:false → 走 §4.2；若持续 needs_captcha → 走 §4.3。

### 4.5 请求报 502（豆包上游错误）
多为风控或网络波动，等 30~60 秒重试即可；频繁出现 → 走 §4.3。

---

## 5. 接入 agent

```text
base_url = http://127.0.0.1:9090/v1
api_key  = 任意非空字符串（服务端默认不校验，如 "1"）
model    = doubao / doubao-think / doubao-pro / doubao-expert
```

- **ZCode**：配置里已有"豆包" provider（kind=openai-compatible，指向 9090），
  直接在设置里切换 provider 为"豆包"、模型选 `doubao` 或 `doubao-think` 即可。
- **Cline / Continue / Cherry Studio 等 OpenAI 兼容客户端**：填上面三项。

### 多轮上下文
服务端自动维护对话线程。OpenAI SDK 场景用 `conversation_id` 续接：
```text
首次响应返回 conversation_id，后续请求带上即可延续上下文。
```

---

## 6. Linux 服务器（Docker）启动流程

适用于 Ubuntu/Debian 服务器，容器化部署。完整部署（构建 + 首次扫码登录）见 `DEPLOY_LINUX.md`，
本章只讲**日常启动 / 停止 / 重启 / 排障**。

前置：已在服务器上完成一次 `docker compose up -d --build` 并扫码登录成功（登录态存容器卷 `./profile`）。

### 6.1 查状态

```bash
# 容器是否在跑
docker ps | grep doubao2api

# 服务健康（DOUBAO_API_KEY 换成你部署时设置的值）
curl -s http://127.0.0.1:9090/health -H "Authorization: Bearer $DOUBAO_API_KEY"
# 期望 {"status":"ok","logged_in":true,...}
```

| 现象 | 含义 | 怎么办 |
|---|---|---|
| `logged_in:true` | 服务正常 | 直接用 |
| `logged_in:false` | 登录态失效 | 走 §6.5 重新扫码登录 |
| `not_ready` / 容器不在 | 服务没启动 | 走 §6.2 |
| 端口 9090 拒绝连接 | 容器没起或防火墙挡了 | 先 §6.2，再查防火墙 |

### 6.2 启动 / 重启

```bash
cd /opt/doubao2api   # 项目所在目录

# 首次或代码有改动时（重建镜像）
docker compose up -d --build

# 日常重启（改完配置/遇到风控后刷新）
docker compose restart doubao2api

# 只看启动日志，出现 "Ready! ... fetch_hook=True" 即就绪
docker compose logs -f doubao2api
```

### 6.3 停止

```bash
cd /opt/doubao2api
docker compose stop doubao2api     # 停止但保留容器/数据
docker compose down                # 完全移除容器（登录态在卷里，不丢）
```

### 6.4 配置改动后生效

改过 `docker-compose.yml`（如换 `DOUBAO_API_KEY`）必须重建：
```bash
docker compose up -d --build
```

### 6.5 重新扫码登录（登录态失效时）

登录态存容器卷 `./profile`，平时不掉。失效（`logged_in:false`）时：
```bash
cd /opt/doubao2api
API_KEY=$(grep DOUBAO_API_KEY docker-compose.yml | awk -F'"' '{print $2}')

# 1. 生成二维码存成本地图片
curl -s -X POST http://127.0.0.1:9090/v1/session/qr-login \
  -H "Authorization: Bearer $API_KEY" \
  | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('qr.png','wb').write(base64.b64decode(d['qr_image_base64']))"

# 2. 把 qr.png 拷到手机/本地，用「豆包 App → 扫一扫」扫码
#    （本地 Windows 也可以：scp 回来打开）

# 3. 轮询直到 status=success
curl -s http://127.0.0.1:9090/v1/session/qr-login -H "Authorization: Bearer $API_KEY"
```

### 6.6 排障

| 现象 | 处理 |
|---|---|
| 接口报 `710022004`（验证码） | 先降频（agent 请求间隔 ≥5s）；持续触发说明机房 IP 风控高，见下 |
| 频繁验证码、`needs_captcha:true` | `docker compose restart` 刷新；仍频繁 → 删 `./profile` 重新扫码登录让账号翻篇 |
| 机房 IP 持续风控 | 换家用网络跑（本机 Windows 方案），或接受较低频率 |
| `logged_in:false` | §6.5 重新扫码 |
| 公网访问超时 | 检查安全组/防火墙放行 9090，或改用 SSH 隧道（见下） |

SSH 隧道（不开公网端口，最安全）：
```bash
# 本地执行，把服务器 9090 映射到本地
ssh -L 9090:127.0.0.1:9090 user@服务器IP
# 然后 agent 指向 http://127.0.0.1:9090/v1，api_key 填 DOUBAO_API_KEY
```

### 6.7 接入 agent（Linux 部署时）

```text
base_url = http://服务器IP:9090/v1     # 走 SSH 隧道则填 http://127.0.0.1:9090/v1
api_key  = <部署时设置的 DOUBAO_API_KEY>
model    = doubao / doubao-think / doubao-pro / doubao-expert
```

ZCode / Cline 等 OpenAI 兼容客户端直接填上面三项。
