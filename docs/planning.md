# Planning 模块

Planning 模块提供 `write_todos` 能力，用于让 Agent 在复杂任务中维护结构化任务清单。

## 状态模型

每个任务包含：

```text
id
content
status
created_at
updated_at
```

支持状态：

```text
pending
in_progress
completed
blocked
cancelled
```

## API

当前先使用内存仓库，后续会替换为 PostgreSQL 持久化。

读取任务清单：

```http
GET /api/v1/planning/sessions/{session_id}/todos
```

写入任务清单：

```http
PUT /api/v1/planning/sessions/{session_id}/todos
```

请求体：

```json
{
  "todos": [
    {
      "id": "1",
      "content": "拆解任务",
      "status": "completed"
    },
    {
      "id": "2",
      "content": "实现 write_todos",
      "status": "in_progress"
    }
  ]
}
```

清空任务清单：

```http
DELETE /api/v1/planning/sessions/{session_id}/todos
```

## 设计约定

- `write_todos` 是替换式写入：请求中的 `todos` 会成为该会话新的完整任务清单。
- 相同 `id` 的任务会保留 `created_at`。
- 任务内容或状态发生变化时更新 `updated_at`。
- 同一个请求中不允许重复 `id`。
- 空白 `session_id`、空白任务 `id`、空白任务内容都会被拒绝。
