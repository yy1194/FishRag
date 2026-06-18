# 可观测性

阶段 8 已补齐基础可观测性闭环：API 请求指标、trace context、Prometheus 抓取配置和 Grafana Dashboard。

## API 指标

FastAPI 暴露 Prometheus text format：

```text
GET /api/v1/metrics
```

当前指标：

| 指标 | 类型 | 说明 |
| --- | --- | --- |
| `fishrag_app_info` | gauge | 服务名和环境信息 |
| `fishrag_http_requests_total` | counter | HTTP 请求总数，按 method、path、status_code 标记 |
| `fishrag_http_request_duration_seconds` | histogram | HTTP 请求耗时，按 method、path 标记 |

示例：

```bash
curl http://localhost:8000/api/v1/metrics
```

## Trace Context

API 中间件支持 W3C `traceparent` 请求头。

- 如果请求带合法 `traceparent`，系统会复用 trace id 并生成新的 span id。
- 如果请求没有 `traceparent`，系统会生成新的 trace id 和 span id。
- 响应头会返回新的 `traceparent`。
- JSON 日志会包含 `request_id`、`trace_id`、`span_id`。

示例：

```bash
curl -H "traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01" \
  http://localhost:8000/api/v1/health
```

## Prometheus

Prometheus 配置文件：

```text
docker/prometheus/prometheus.yml
```

默认抓取：

```text
host.docker.internal:8000/api/v1/metrics
```

这适合 API 直接跑在宿主机、Prometheus 跑在 Docker 容器中的本地开发方式。如果后续 API 也容器化，可以把 target 改成 API 服务名。

启动：

```bash
docker compose up -d prometheus
```

访问：

```text
http://localhost:9090
```

## Grafana

Grafana 已配置 Prometheus 数据源和 `FishRag API` Dashboard。

启动：

```bash
docker compose up -d grafana
```

访问：

```text
http://localhost:3000
```

默认账号：

```text
admin / fishrag
```

可以通过 `.env` 修改：

```text
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=fishrag
```

## 后续扩展

- 接入真正的 OpenTelemetry SDK 和 OTLP exporter。
- 增加模型调用、Embedding、Reranker、OpenSearch、数据库查询的耗时指标。
- 增加后台任务、文档入库、评测任务的业务指标。
- 增加告警规则，例如 5xx 比例、P95 延迟、评测任务失败率。
