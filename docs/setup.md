# FishRag 本地开发说明

## 1. 环境准备

- Python 3.11 到 3.13
- Node.js 20+
- Docker Desktop 或兼容 Docker Compose 的环境

## 2. 环境变量

复制 `.env.example` 为 `.env`，根据本机端口和模型服务地址调整配置。

```powershell
Copy-Item .env.example .env
```

后端启动时会自动读取项目根目录下的 `.env` 文件；如果同名系统环境变量已经存在，则系统环境变量优先。

## 3. 启动中间件

项目需要 PostgreSQL + pgvector、Redis、OpenSearch。当前已经提供 `docker-compose.yml`：

```powershell
docker compose up -d postgres redis opensearch
```

如果你的本机已经占用 `5432`、`6379` 或 `9200`，请先修改 `.env` 中的端口。

如果 Docker Hub 拉取镜像出现 `EOF` 或超时，请参考 `docs/middleware.md` 配置镜像源或覆盖镜像地址。

## 4. 接入云端模型

项目默认按 DeepSeek 云端聊天模型配置，不需要本机部署大模型。

在 `.env` 中把下面的 Key 替换为你的 DeepSeek API Key：

```text
FISHRAG_LLM_API_KEY=sk-...
```

默认聊天模型：

```text
FISHRAG_CHAT_MODEL=deepseek-v4-flash
FISHRAG_LLM_THINKING=disabled
```

默认 API 地址：

```text
https://api.deepseek.com
```

DeepSeek 负责聊天模型。Embedding 和 Reranker 默认使用 SiliconFlow 的 `BAAI/bge-m3` 和 `BAAI/bge-reranker-v2-m3`，两组 API Key 可以独立配置。

如果后续要切换到其他 OpenAI-compatible 云厂商，只需要替换对应的 `BASE_URL`、`API_KEY` 和模型名。

## 5. 后端开发

安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

启动 API：

```powershell
uvicorn fishrag_api.main:app --reload --app-dir apps/api --host 127.0.0.1 --port 8000
```

健康检查地址：

```text
http://127.0.0.1:8000/api/v1/health
```

## 6. 前端开发

```powershell
cd apps/web
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

## 7. 当前注意事项

- 本阶段只完成工程骨架和基础模块，不会主动连接数据库。
- 第一次启动中间件前，请确认 Docker Desktop 已运行。
- 模型服务默认使用 DeepSeek 云端聊天接口，并使用 SiliconFlow 的 Embedding、Reranker 接口。
