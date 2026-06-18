# 部署说明

阶段 8 已补齐基础 Docker 镜像和本地部署路径。当前部署目标是本地或单机环境，后续可以扩展到 Kubernetes。

## 服务

Docker Compose 包含：

| 服务 | 说明 | 默认端口 |
| --- | --- | --- |
| `postgres` | PostgreSQL + pgvector | `5432` |
| `redis` | 缓存和任务队列基础设施 | `6379` |
| `opensearch` | BM25 关键词检索 | `9200` |
| `prometheus` | 指标抓取 | `9090` |
| `grafana` | 指标看板 | `3000` |
| `api` | FastAPI 后端，位于 `app` profile | `8000` |
| `web` | React 前端，位于 `app` profile | `5173` |

## 仅启动中间件

```bash
docker compose up -d postgres redis opensearch prometheus grafana
```

## 启动完整应用

复制环境变量：

```bash
copy .env.example .env
```

在 `.env` 中填入模型服务 API Key 后启动：

```bash
docker compose --profile app up -d --build
```

访问：

```text
API:        http://localhost:8000/api/v1/health
Web:        http://localhost:5173
Prometheus: http://localhost:9090
Grafana:    http://localhost:3000
```

## 数据库迁移

宿主机运行：

```bash
python -m alembic upgrade head
```

容器中运行：

```bash
docker compose --profile app exec api alembic upgrade head
```

## 镜像构建

后端镜像：

```bash
docker build -f apps/api/Dockerfile -t fishrag-api:local .
```

前端镜像：

```bash
docker build -f apps/web/Dockerfile -t fishrag-web:local apps/web
```

## 轻量压测

项目提供一个无第三方依赖的 HTTP smoke load 脚本：

```bash
python tools/perf_smoke.py --url http://localhost:8000/api/v1/health --requests 200 --concurrency 20
```

输出包含成功数、错误数、RPS、状态码分布、平均延迟、P95 延迟和最大延迟。

## 超时和重试

模型、Embedding、Reranker 和 OpenSearch 客户端共享以下环境变量：

```text
FISHRAG_HTTP_TIMEOUT_SECONDS=60
FISHRAG_HTTP_MAX_ATTEMPTS=3
FISHRAG_HTTP_RETRY_BACKOFF_SECONDS=0.2
```

重试策略：

- 超时和网络错误会重试。
- HTTP `408`、`409`、`425`、`429`、`500`、`502`、`503`、`504` 会重试。
- 普通 `4xx` 业务错误不会重试。

## 后续生产化

- 使用外部托管 PostgreSQL、Redis、OpenSearch。
- 将 FastAPI 本地后台任务替换为 Celery/RQ worker。
- 接入 OTLP exporter 和集中式日志。
- 增加 Nginx/Ingress、TLS、鉴权网关和灰度发布流程。
