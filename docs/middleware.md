# FishRag 中间件启动说明

FishRag 本地开发依赖三个中间件：

- PostgreSQL + pgvector：关系数据和向量数据。
- Redis：缓存和异步任务队列。
- OpenSearch：关键词检索和 BM25 召回。

## 1. 启动命令

```powershell
docker compose up -d postgres redis opensearch
```

查看状态：

```powershell
docker compose ps
```

查看日志：

```powershell
docker compose logs -f postgres redis opensearch
```

## 2. Docker Hub 拉取失败

如果出现类似错误：

```text
failed to resolve reference ... registry-1.docker.io ... EOF
```

通常是 Docker Hub 网络或镜像源问题。可以任选一种方式处理。

### 方式 A：配置 Docker Desktop 镜像加速

在 Docker Desktop 的 Docker Engine 配置里添加你可用的镜像源，例如企业内部镜像源或云厂商提供的镜像加速地址：

```json
{
  "registry-mirrors": [
    "https://your-docker-registry-mirror.example"
  ]
}
```

保存并重启 Docker Desktop 后重新执行：

```powershell
docker compose up -d postgres redis opensearch
```

### 方式 B：用 `.env` 覆盖镜像地址

`.env.example` 已提供可覆盖的镜像变量：

```text
POSTGRES_IMAGE=pgvector/pgvector:pg16-bookworm
REDIS_IMAGE=redis:7-alpine
OPENSEARCH_IMAGE=opensearchproject/opensearch:2.15.0
```

如果你有镜像代理或私有镜像仓库，可以在 `.env` 中改成：

```text
POSTGRES_IMAGE=your-registry.example/pgvector/pgvector:pg16-bookworm
REDIS_IMAGE=your-registry.example/library/redis:7-alpine
OPENSEARCH_IMAGE=your-registry.example/opensearchproject/opensearch:2.15.0
```

然后重新启动：

```powershell
docker compose up -d postgres redis opensearch
```

## 3. 端口占用

默认端口：

```text
PostgreSQL: 5432
Redis: 6379
OpenSearch: 9200
OpenSearch Performance Analyzer: 9600
```

如果端口被占用，在 `.env` 中修改：

```text
POSTGRES_PORT=15432
REDIS_PORT=16379
OPENSEARCH_PORT=19200
```

同步修改应用连接串：

```text
FISHRAG_DATABASE_URL=postgresql+asyncpg://fishrag:fishrag@localhost:15432/fishrag
FISHRAG_REDIS_URL=redis://localhost:16379/0
FISHRAG_OPENSEARCH_URL=http://localhost:19200
```

## 4. 验证命令

PostgreSQL：

```powershell
docker compose exec postgres pg_isready -U fishrag -d fishrag
```

pgvector：

```powershell
docker compose exec postgres psql -U fishrag -d fishrag -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

向量查询：

```powershell
docker compose exec postgres psql -U fishrag -d fishrag -c "SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector AS distance;"
```

Redis：

```powershell
docker compose exec redis redis-cli ping
```

OpenSearch：

```powershell
curl http://localhost:9200
```

## 5. OpenSearch 安全插件

本地开发默认禁用 OpenSearch Security Plugin：

```text
OPENSEARCH_DISABLE_SECURITY=true
```

OpenSearch 2.12 以后，如果不禁用安全插件，需要提供 `OPENSEARCH_INITIAL_ADMIN_PASSWORD`。本项目本地开发阶段先使用无认证 HTTP，后续生产部署再补 TLS、账号和权限配置。
