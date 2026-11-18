#!/bin/bash
# doubao2api 一键启动（有头模式 + 复用已登录 profile）
# 用法: ./start.sh
# 注意: 如果服务已在运行（端口被占用），会直接提示而不是重复启动。
cd "$(dirname "$0")"

# 登录态目录：优先用外部传入的 DOUBAO_BROWSER_DATA，否则默认 ~/.doubao_browser
export DOUBAO_BROWSER_DATA="${DOUBAO_BROWSER_DATA:-$HOME/.doubao_browser}"
export DOUBAO_HEADLESS=false
export DOUBAO_PORT="${DOUBAO_PORT:-9090}"

PORT="${DOUBAO_PORT:-9090}"

# 检查端口是否已被占用（说明服务已在运行）
if netstat -ano 2>/dev/null | grep ":${PORT} " | grep -q LISTENING; then
  echo "端口 ${PORT} 已被占用 —— 服务可能已经在运行。"
  curl -s "http://127.0.0.1:${PORT}/health" 2>/dev/null && echo
  echo "无需重复启动。若确实想重启，请先停掉占用端口的进程。"
  exit 0
fi

python -m doubao2api
