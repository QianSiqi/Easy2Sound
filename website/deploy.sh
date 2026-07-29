#!/bin/bash
# Easy2Sound 一键部署脚本

echo "=== Easy2Sound 部署 ==="

# 安装后端依赖
echo "[1/3] 安装后端依赖..."
cd api && npm install --production && cd ..

# 启动后端（后台运行）
echo "[2/3] 启动 API 服务..."
cd api
if [ -f .env ]; then
    export $(cat .env | xargs)
fi
nohup node server.js > ../api.log 2>&1 &
echo "API PID: $!"
cd ..

# 启动前端（后台运行）
echo "[3/3] 启动前端服务..."
nohup python3 serve.py > ../frontend.log 2>&1 &
echo "Frontend PID: $!"

echo ""
echo "✅ 部署完成！"
echo "   前端: http://${HOST:-localhost}:8080"
echo "   API:  http://${HOST:-localhost}:${PORT:-3000}"
echo "   日志: api.log / frontend.log"
