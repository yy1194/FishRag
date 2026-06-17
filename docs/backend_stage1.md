# 阶段 1：后端基础能力

阶段 1 提供后端生产化基础能力：

- FastAPI 应用入口和健康检查。
- 统一错误响应。
- 请求追踪 ID 和结构化日志。
- SQLAlchemy 数据库模型。
- Alembic PostgreSQL 迁移。
- JWT 登录鉴权和基础 RBAC。

当前状态：已完成并通过本地 PostgreSQL/pgvector 迁移验证。

## 数据库

当前模型覆盖：

- `users`
- `chat_sessions`
- `messages`
- `documents`
- `document_chunks`
- `agent_tasks`
- `approvals`
- `memories`

执行迁移：

```powershell
alembic upgrade head
```

已验证迁移版本：

```text
20260617_0001
```

## 认证

登录：

```http
POST /api/v1/auth/token
```

当前用户：

```http
GET /api/v1/auth/me
Authorization: Bearer <token>
```

管理员创建用户：

```http
POST /api/v1/auth/register
Authorization: Bearer <admin-token>
```

## 错误响应

统一错误响应格式：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [],
    "request_id": "..."
  }
}
```

## 请求追踪

每个响应都会包含：

```text
X-Request-ID
```

如果请求头传入 `X-Request-ID`，系统会复用它；否则自动生成 UUID。

## 验证

阶段 1 当前通过以下检查：

```powershell
ruff check .
mypy apps packages tests
python -m pytest
python -m compileall apps/api packages tests migrations
```

数据库验证结果：

- `pg_extension` 中存在 `vector`，版本为 `0.8.2`。
- `public` schema 中存在 `users`、`chat_sessions`、`messages`、`documents`、`document_chunks`、`agent_tasks`、`approvals`、`memories`。
- `alembic_version` 当前为 `20260617_0001`。
