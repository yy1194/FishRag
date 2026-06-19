# 验收与演示

本文件用于阶段 8 之后的本地验收和项目演示。目标是快速确认 API、可观测性和 RAG 评估基础闭环可用，再进入真实文档上传和问答演示。

## 前置条件

- API 已启动，并暴露 `http://localhost:8000/api/v1`。
- 如果使用数据库相关接口，已执行 `alembic upgrade head`。
- `.env` 已填入需要的模型服务 Key。

基础验收脚本不会调用真实聊天模型、Embedding 或 Reranker。它使用确定性的评估打分接口，因此适合做服务启动后的第一轮 smoke check。

## 一键验收

```bash
python tools/acceptance_smoke.py --base-url http://localhost:8000/api/v1
```

预期输出示例：

```text
FishRag acceptance smoke: http://localhost:8000/api/v1
[PASS] health status=200 duration_ms=12.34 - service ok with request and trace headers
[PASS] metrics status=200 duration_ms=5.67 - prometheus metrics exported
[PASS] rag_score status=200 duration_ms=8.90 - rag evaluation scoring pipeline works
summary: 3/3 passed
```

机器可读输出：

```bash
python tools/acceptance_smoke.py --base-url http://localhost:8000/api/v1 --json
```

## 验收项

| 检查项 | 接口 | 验证内容 |
| --- | --- | --- |
| `health` | `GET /health` | 服务返回 `status=ok`，响应头包含 `X-Request-ID` 和 `traceparent` |
| `metrics` | `GET /metrics` | Prometheus text format 包含 `fishrag_app_info` 和 `fishrag_http_requests_total` |
| `rag_score` | `POST /evaluations/rag/score` | RAG 评估打分接口返回 `total_examples=1` 和 `recall@1=1.0` |

## 常见失败定位

- `health` 失败：检查 API 是否启动、端口是否为 `8000`、`FISHRAG_API_PREFIX` 是否仍为 `/api/v1`。
- `metrics` 失败：检查 `RequestContextMiddleware` 和 `/metrics` 路由是否正常加载。
- `rag_score` 失败：检查 `evaluations` 路由是否注册，或请求/响应 schema 是否发生变更。

## 轻量压测

验收通过后，可以对健康检查接口做轻量压力测试：

```bash
python tools/perf_smoke.py --url http://localhost:8000/api/v1/health --requests 200 --concurrency 20
```

该脚本输出成功数、错误数、RPS、状态码分布、平均延迟、P95 延迟和最大延迟。

## 演示流程

1. 启动完整应用：`docker compose --profile app up -d --build`。
2. 执行数据库迁移：`docker compose --profile app exec api alembic upgrade head`。
3. 运行验收脚本：`python tools/acceptance_smoke.py --base-url http://localhost:8000/api/v1`。
4. 打开前端：`http://localhost:5173`。
5. 上传 PDF、TXT、Markdown、CSV 或 DOCX 文档，确认状态从 `uploaded` 流转到 `indexed`。
6. 在聊天界面提问，确认回答包含引用片段和文档来源。
7. 在评估面板创建 RAG 评测任务，查看 aggregate 指标和样本明细。
