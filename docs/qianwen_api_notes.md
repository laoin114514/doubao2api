# 千问 (Qianwen) API 逆向工程记录

## 日期
2026-05-24

## API 端点

```
POST https://chat2.qianwen.com/api/v2/chat
```

Query参数（固定模板）：
```
?biz_id=ai_qwen&fe_version=1.0.0&chat_client=h5&device=pc&fr=pc&pr=qwen
&ut={device_id}&la=zh-CN&tz=Pacific%2FAuckland&wv=2.9.3&ve=2.9.3
&nonce={random_11chars}&timestamp={unix_ms}
```

## 签名机制

阿里安全SDK（百夏/baxia），需要4步签名：

```javascript
// 1. 获取签名头 + 重写URL
const { signedHeader, signedUrl } = await window.__QIANWEN_CHAT_SDK__.qwenSign(baseUrl);

// 2. ET签名（防重放）
const bxEt = window.etSign(signedUrl);

// 3. UA指纹
const bxUa = window.__baxia__.postFYModule.getFYToken();

// 4. UMID设备标识
const bxUmid = window.__baxia__.postFYModule.getUidToken();
```

### signedHeader 返回的头：
| Header | 说明 |
|--------|------|
| `clt-acs-sign` | 请求签名（HMAC） |
| `clt-acs-reqt` | 请求时间戳 |
| `clt-acs-request-params` | 参与签名的query参数列表 |
| `eo-clt-dvidn` | 设备标识（加密） |
| `eo-clt-sacsft` | 安全令牌 |
| `eo-clt-snver` | 签名版本 ("lv") |
| `eo-clt-actkn` | 访问令牌 |
| `eo-clt-acs-ve` | ACS版本 ("1.0.0") |
| `clt-acs-caer` | 固定值 "vrad" |
| `eo-clt-acs-kp` | 空字符串 |

### 额外需要手动添加的头：
| Header | 来源 |
|--------|------|
| `bx_et` | `etSign(signedUrl)` |
| `bx-ua` | `postFYModule.getFYToken()` |
| `bx-umidtoken` | `postFYModule.getUidToken()` |
| `x-platform` | 固定 "pc_tongyi" |
| `x-device-id` | UUID格式设备ID |
| `x-chat-id` | 请求ID |
| `x-chat-biz` | JSON: `{chatId, agentId, enableWebp}` |

## 请求体格式

```json
{
  "req_id": "hex32",
  "parent_req_id": "",
  "messages": [{
    "mime_type": "text/plain",
    "content": "用户消息",
    "meta_data": {"ori_query": "用户消息"},
    "status": "complete"
  }],
  "scene": "chat",
  "sub_scene": "",
  "scene_param": "new_chat | continue_chat",
  "session_id": "hex32",
  "biz_id": "ai_qwen",
  "topic_id": "",
  "model": "Qwen",
  "from": "default",
  "protocol_version": "v2",
  "messages_merge": false,
  "chat_client": "h5",
  "deep_search": "0",
  "temporary": true
}
```

### model 字段已知值
从 `GET https://chat2-api.qianwen.com/api/v1/model/list` 获取的完整列表：

| modelCode | 显示名 | 说明 | UI可见 |
|-----------|--------|------|--------|
| `Qwen` | Qwen3.6-千问 | 综合AI助手（默认） | ✅ |
| `Qwen3.7-Max` | Qwen3.7-Max | 千问最新旗舰，擅长代码 (NEW) | ✅ |
| `Qwen3.5-Plus` | Qwen3.5-Plus | 最新大语言模型 | 隐藏 |
| `Qwen3.5-Flash` | Qwen3.5-Flash | 简单任务，速度快 | ✅ |
| `Qwen3-Max` | Qwen3-Max | 日常通用型 | ✅ |
| `Qwen3-Max-Thinking-Preview` | Qwen3-Max-Thinking | 多步骤推理 | ✅ |
| `Qwen3-Coder` | Qwen3-Coder | 代码生成 | ✅ |
| `Qwen3-Flash` | Qwen3-Flash | 简单任务，速度快 | 隐藏 |
| `Qwen3-Plus` | Qwen3-Plus | 全能语言模型 | 隐藏 |
| `Qwen3-VL-Plus` | Qwen3-VL-Plus | 视觉理解 | 隐藏 |
| `Qwen3-Coder-Flash` | Qwen3-Coder-Flash | 闪电代码生成 | 隐藏 |
| `Qwen3-VL-235B-A22B` | Qwen3-VL-235B-A22B | 多模态 | 隐藏 |
| `Qwen3-VL-32B` | Qwen3-VL-32B | 视觉语言模型 | 隐藏 |
| `Qwen3-VL-30B-A3B` | Qwen3-VL-30B-A3B | MoE视觉 | 隐藏 |
| `Qwen3-235B-A22B-2507` | Qwen3-235B-A22B-2507 | 最强MoE | 隐藏 |
| `Qwen3-Omni-Flash` | Qwen3-Omni-Flash | 全模态 | 隐藏 |
| `Qwen3-Next-80B-A3B` | Qwen3-Next-80B-A3B | 下一代MoE | 隐藏 |
| `Qwen3-30B-A3B-2507` | Qwen3-30B-A3B-2507 | MoE模型 | 隐藏 |

注意：隐藏模型（show=false）也可以通过API直接调用。

### deep_search 字段（思考/搜索模式）
- `"0"` — 普通对话（无思考）
- `"1"` — **思考模式**（网页端"思考"按钮高亮时的状态）

注意：网页端的"思考"按钮实际发送的就是 `deep_search: "1"`，不是单独的 `thinking` 字段。

#### ✅ 思考模式与工具调用兼容（已修复）

~~之前认为 `deep_search="1"` + tools 不兼容，实际是 prompt 模板格式问题。~~

**根本原因**：旧的 `<tool_calls><invoke>` 格式会导致 thinking 模式进入 `plan_cot` 循环。
切换到官方 `<tool_call>{"name":..., "arguments":...}</tool_call>` 格式后，thinking + tools 正常工作。

**关键发现**：
- thinking 模式下，模型的 tool call 输出在 `meta_data.multi_load[0].content.think_content` 中
- 主 content 只有 `[(multimodal_chat_think_N)]` 占位符
- think_content 中可能缺少开头 `<tool_call>` 标签，只有 JSON + `</tool_call>`
- 解析器需要容错处理：支持 partial 标签、bare JSON、unquoted values

**服务端处理**：
- `enable_thinking=true` 或 `reasoning_effort` 非 none → `deep_search="1"`
- 工具调用检测同时检查 `think_content` 和主 `content`
- 返回标准 OpenAI 格式的 `tool_calls` + `reasoning_content`

### 思考模式 SSE 格式

开启 `deep_search: "1"` 后，SSE 响应结构变化：

#### mime_type 列表（思考模式）
| mime_type | 说明 |
|-----------|------|
| `signal/post` | 意图分析（同普通模式） |
| `plan_cot/post` | 思考状态标记（content 为空，仅作进度指示） |
| `bar/progress` | 进度标记：`meta.type="deep_thinking"` 思考中，`"deep_thought"` 思考完成 |
| `multi_load/iframe` | **主要内容**（content=回答，meta_data.multi_load=思维链） |

#### 思维链数据位置
```json
{
  "mime_type": "multi_load/iframe",
  "content": "[(multimodal_chat_think_1)]正式回答内容...",
  "meta_data": {
    "multi_load": [{
      "type": "multimodal_chat_think",
      "source_seq": "multimodal_chat_think_1",
      "content": {
        "think_content": "思维链文本（累积式）...",
        "status": "processing | complete",
        "timecost": 3800
      }
    }]
  },
  "status": "processing"
}
```

#### 关键细节
1. **思维链是累积式的** — 每个 chunk 的 `think_content` 包含从头到当前的完整思考
2. **正文 content 以标记开头** — `[(multimodal_chat_think_1)]` 后面才是实际回答
3. **需要剥离标记** — 正文需要去掉 `[(multimodal_chat_think_1)]` 前缀
4. **时序**：先出现 `think_content`（思考中），content 为空或只有标记；思考完成后 content 开始有回答文本
5. `bar/progress` 的 `meta.type` 从 `"deep_thinking"` → `"deep_thought"` 标志思考结束

#### 对应 OpenAI 格式的映射
- `think_content` → `choices[0].delta.reasoning_content`（思维链）
- content（去掉标记后） → `choices[0].delta.content`（正式回答）

## 响应格式（SSE text/event-stream）

### 事件类型（通过 mime_type 区分）

| mime_type | 说明 |
|-----------|------|
| `signal/post` | 意图分析结果（intent） |
| `bar/progress` | 进度标记：`type:"cot"` 开始思考，`type:"generated"` 完成 |
| `bar/iframe` | 搜索来源（sources数组） |
| `multi_load/iframe` | **主要内容**，content字段为累积式全文 |

### 流式内容特点
- **累积式**：每个 `multi_load/iframe` chunk 的 content 包含从头到当前的完整文本
- 需要客户端自行计算 delta（当前content - 上一次content）
- `status: "processing"` 表示生成中，`status: "complete"` 表示该消息完成

### 最终事件
```
event:complete
data:{"error_msg":"","data":{...},"error_code":0,...}
```

### Token用量（在最终chunk的 extra_info.chat_odps.total_usage 中）
```json
{
  "completion_tokens": 605,
  "prompt_tokens": 872,
  "total_tokens": 1477
}
```

### 实际模型信息（extra_info.chat_odps.model_info）
```json
{
  "model": "qwenapp-397b-2026-04-27",
  "audit_result": 1,
  "session_result": 1
}
```

## 已确认的后端模型
- `qwen3.6-plus-2026-05-07` — 短回答/FAQ场景 (model="Qwen")
- `qwenapp-397b-2026-04-27` — 长回答/创作场景 (model="Qwen", 397B参数)
- Qwen3.7-Max — 旗舰模型，擅长代码（model="Qwen3.7-Max"）

## SSE格式差异
- **Qwen (默认)**: 纯 `data:` 行
- **Qwen3.7-Max**: 使用 `event:message\ndata:` 格式（标准SSE）
- 两种格式的 data JSON 结构相同

## 免登录使用
- 设置 `temporary: true` 即可无需登录
- 有使用限制（具体限额未测试）
- 登录后可获得更多配额和历史记录

## Tool Calling 实现（2026-05-24 完成）

### 方案
采用与豆包相同的 **XML Prompt Injection** 方案：
- 将 OpenAI 格式的 tools 定义转换为文本描述，注入到 system prompt
- 模型输出 `<tool_calls>` XML 格式表示工具调用
- 服务端解析 XML 并转换回 OpenAI 格式的 tool_calls 响应

### 核心模块：`doubao2api/tool_calling.py`

#### TOOL_SYSTEM_PROMPT（注入到对话开头）
```
你是一个工具调用助手。你只能通过调用下方列出的工具来获取外部信息或执行操作。

【可用工具列表 - 你只能调用以下工具，严禁调用不在此列表中的工具】
{tool_definitions}

【工具调用格式】
<tool_calls>
<invoke name="工具名">
<parameter name="参数名">参数值</parameter>
</invoke>
</tool_calls>

【严格规则】
1. 绝对禁止调用列表之外的工具名称
2. 工具名必须完全一致（区分大小写）
3. 调用工具时只输出XML，不要解释
4. 可以并行调用多个工具
5. 不需要工具时直接自然语言回答
6. 不要编造数据
7. 禁止使用内置联网搜索
8. 工具返回空/不可读时，主动尝试其他工具解决
```

#### 关键函数
- `build_tool_system_prompt(tools)` — 构建完整 system prompt
- `format_tools_for_prompt(tools)` — OpenAI tools → 文本描述
- `convert_messages_with_tools(messages, tools)` — 完整消息转换
- `parse_tool_calls_xml(text, valid_tool_names)` — 解析模型输出的XML
- `is_tool_call_start(text)` — 检测流式输出中的工具调用开始

### 服务端验证（防止模型编造工具名）
- 从请求的 `tools` 数组提取 `valid_tool_names` 集合
- `parse_tool_calls_xml()` 接受白名单参数
- 如果模型调用了不在白名单中的工具名 → 整个解析返回 None → 作为普通文本返回
- 日志记录非法工具调用（便于调试）

### 已知问题与解决
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 模型调用不存在的工具（如"文档检索"） | prompt不够严格 | 强化prompt + 服务端白名单验证 |
| tool result 为 list 格式时丢失 | 只处理了 str 类型 | 添加 list 格式解析（提取 text parts） |
| PDF 读取返回空后模型放弃 | 缺少重试指导 | 添加规则8：主动尝试其他工具 |
| deep_search=1 + tools 返回空内容 | 旧 `<tool_calls><invoke>` 模板格式冲突 | 切换到官方 `<tool_call>` 格式，解析 think_content |
| OpenCode 流式中断（思维链后无回答） | chunkTimeout 默认太短 | 设置 chunkTimeout=60000ms |

### 测试结果
- ✅ 单工具调用（非流式）
- ✅ 并行多工具调用（流式）
- ✅ 有工具但不需要调用 → 直接回答
- ✅ 非法工具名被拦截 → 降级为文本
- ✅ list 格式 tool result 正确解析

## 实现方案

采用与豆包相同的 Playwright in-browser fetch 方案：
1. Playwright 打开 qianwen.com 页面
2. 等待安全SDK加载（`__QIANWEN_CHAT_SDK__`, `etSign`, `__baxia__`）
3. 通过 `page.evaluate()` 在浏览器内执行签名+fetch
4. 通过 `expose_function` 桥接SSE chunks回Python
5. Python侧将累积content转换为OpenAI delta格式

## 文件
- `doubao2api/qianwen_client.py` — 浏览器客户端实现
- `doubao2api/unified_server.py` — 已集成路由（model: qianwen-*）
- `doubao2api/tool_calling.py` — Tool Calling 模块（XML prompt injection + 解析）

## 部署配置
```bash
QIANWEN_ENABLED=true
QIANWEN_HEADLESS=true
QIANWEN_BROWSER_DATA=/opt/doubao2api/.qianwen_browser
```

## 部署状态（2026-05-24）

**已上线运行**，与豆包共用同一端点：
- 端点: `http://103.237.92.203:9090/v1`
- Key: `sk-doubao-6c109ee905c2c5150fa43a62acc0e056`
- 通过 model 字段路由：`qianwen-*` → 千问，`doubao-*` → 豆包

### OpenAI兼容模型名映射
| model (请求用) | 实际调用 | 说明 |
|---------------|---------|------|
| `qianwen-max` | Qwen3.7-Max | 旗舰模型 |
| `qianwen-max-think` | Qwen3.7-Max + deep_search=1 | 旗舰+思考（无工具时生效） |
| `qianwen` | Qwen3.6-千问 | 默认综合 |
| `qianwen-coder` | Qwen3-Coder | 代码生成 |
| `qianwen-think` | Qwen3-Max-Thinking-Preview | 深度推理（原生思考模型） |
| `qianwen-flash` | Qwen3.5-Flash | 快速响应 |
| `qianwen-search` | Qwen3.7-Max + deep_search=1 | 深度搜索/思考 |

也支持直接传原始 modelCode（如 `Qwen3.7-Max`、`Qwen3-235B-A22B-2507`）。

### 已修复的部署问题
1. `playwright_stealth` 2.x API 变更 → 用 `apply_stealth_async`
2. VPS网络慢导致 `networkidle` 超时 → 改用 `domcontentloaded`
3. Qwen3.7-Max SSE 末尾有裸 `true` 值 → 跳过非dict chunks
4. debug `sed` 注入导致语法错误 → `git checkout` 恢复

### 功能完成度
| 功能 | 状态 | 备注 |
|------|------|------|
| 基础聊天（流式/非流式） | ✅ | 所有模型 |
| Tool Calling | ✅ | 官方 `<tool_call>` 格式 prompt injection |
| 服务端工具名验证 | ✅ | 白名单拦截 |
| 深度搜索 | ✅ | deep_search=1 |
| 思考模式（thinking） | ✅ | deep_search="1"，思维链在 meta_data.multi_load |
| 思考+工具调用共存 | ✅ | tool call 在 think_content 中，解析器容错处理 |
| 多轮对话 | ❌ | 每次新session |
| 图片/文件上传 | ❌ | 未实现 |
| 登录态 | ❌ | 仅 temporary=true |

## 待探索
- [x] 切换到 Qwen3.7-Max 模型
- [x] VPS部署并验证端到端可用
- [x] Tool Calling 支持
- [x] 服务端工具名验证
- [x] **思考模式（thinking）** — `deep_search="1"` + 解析 `meta_data.multi_load[0].content.think_content`
- [x] **思考+工具共存** — 官方 `<tool_call>` 格式 + think_content 解析，已验证可用
- [ ] 登录态下的额外功能
- [ ] 多轮对话（topic_id复用）
- [ ] 速率限制和配额
- [ ] 图片/文件上传
- [ ] 隐藏模型（Qwen3-VL系列、Qwen3-Omni-Flash等）的可用性测试
