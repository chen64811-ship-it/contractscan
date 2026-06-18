# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

ContractScan — AI 合同风险审查工具。上传合同 PDF/图片/文本，用 LLM 自动识别风险条款和缺失条款，给出风险评分和修改建议。

## 常用命令

```bash
# 安装依赖（GPU 环境）
pip install paddlepaddle-gpu==2.6.2 -i https://mirror.baidu.com/pypi/simple
pip install -r backend/requirements.txt

# 启动开发服务器
cd backend && uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# 运行测试
pytest
pytest -v -k <test_name>
```

## 架构

- **后端框架**: FastAPI（非 Flask），入口 `backend/app.py`
- **前端**: 单文件 `frontend/index.html`，内嵌 CSS/JS，无构建工具
- **LLM**: 通过 OpenAI 兼容 SDK 调用 DeepSeek API（`services/contract_analyzer.py`），系统提示词要求返回结构化 JSON（风险条款 + 缺失条款 + 评分）
- **文本提取**: 多格式支持 — PDF（PyMuPDF + pdfminer 多进程提取 + OCR 扫描页回退）、Word（格式保留）、Excel、图片 OCR（PaddleOCR，支持 GPU）
- **进度追踪**: `progress_store.py` 提供线程安全的 in-memory 进度存储，用于文件解析进度轮询
- **配置**: `.env` 文件管理敏感配置（API Key 等），`config.py` 读取通用配置，`config_manager.py` 管理 LLM 配置（当前未被主路由使用，路由直接从环境变量读取）

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/api/analyze` | 上传文件 + 分析 |
| POST | `/api/analyze-text` | 粘贴文本 + 分析 |
| POST | `/api/debug-analyze` | 调试：返回 LLM 原始响应 |
| GET | `/api/health` | 健康检查 |

## 注意事项

- `.env` 文件目前在项目根目录，但 `docker-compose.yml` 和 `config_manager.py` 期望它在 `backend/` 下。Docker 部署时需确保路径一致。
- `contract_analyzer.py` 的 `analyze_contract()` 最大处理 12000 字符，超长合同会被截断。
- OCR 有 GPU/CPU 两种模式，通过 `.env` 中的 `OCR_USE_GPU` 控制。GPU 模式下使用线程池（非进程池），因为 GPU 资源在线程间共享更好。
- 前端 `SAMPLE_CONTRACT` 是硬编码的英文示例合同，用于演示功能。
