# 推荐沙箱镜像：Python 3.12 + 常用测试工具
# 构建：codeguild sandbox-build
# 或：docker build -t multi-agent-sandbox:py312 -f sandbox/sandbox.Dockerfile sandbox/
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir pytest pytest-asyncio

WORKDIR /workspace
