# 阶段 5：会话与记忆

当前已完成会话与长期记忆基础闭环：

- 多会话创建、列表、重命名、归档、删除和恢复。
- 会话消息保存和读取。
- 使用消息 `metadata` 保存工具调用、引用、Agent 中间状态。
- 会话摘要生成和恢复。
- 长期记忆创建、检索、更新和删除。
- 长期记忆 `enabled` 用户开关和 metadata 审计记录。

## 鉴权

阶段 5 接口都依赖 Bearer Token。会话和记忆都按当前用户隔离。

```http
Authorization: Bearer <token>
```

## 会话接口

创建会话：

```http
POST /api/v1/sessions
Content-Type: application/json
```

```json
{
  "title": "高血压资料问答"
}
```

列出会话：

```http
GET /api/v1/sessions
GET /api/v1/sessions?status=archived
GET /api/v1/sessions?include_deleted=true
```

读取会话详情和消息：

```http
GET /api/v1/sessions/{session_id}
GET /api/v1/sessions/{session_id}/messages
```

重命名或归档会话：

```http
PATCH /api/v1/sessions/{session_id}
Content-Type: application/json
```

```json
{
  "title": "高血压讨论",
  "status": "archived"
}
```

软删除和恢复：

```http
DELETE /api/v1/sessions/{session_id}
POST /api/v1/sessions/{session_id}/restore
```

当前删除是软删除，会把 `chat_sessions.status` 设置为 `deleted`，不会物理删除历史消息。

## 消息接口

追加消息：

```http
POST /api/v1/sessions/{session_id}/messages
Content-Type: application/json
```

```json
{
  "role": "assistant",
  "content": "根据知识库证据，高血压治疗需要结合风险分层。[C1]",
  "metadata": {
    "citations": ["C1"],
    "tool_calls": [
      {
        "name": "rag_search",
        "status": "completed"
      }
    ]
  }
}
```

支持角色：

- `system`
- `user`
- `assistant`
- `tool`

工具调用结果、Agent 中间状态、引用列表和模型调用信息都可以放入 `metadata`。

## 会话摘要

生成并保存摘要：

```http
POST /api/v1/sessions/{session_id}/summary
Content-Type: application/json
```

```json
{
  "max_messages": 20,
  "max_chars": 1200
}
```

当前摘要生成是确定性实现：按消息顺序提取角色和内容预览，写回 `chat_sessions.summary`。后续可以替换为模型摘要。

## 长期记忆接口

创建记忆：

```http
POST /api/v1/memories
Content-Type: application/json
```

```json
{
  "scope": "profile",
  "key": "output_style",
  "value": "喜欢简洁分步骤输出",
  "enabled": true,
  "metadata": {
    "source": "manual"
  }
}
```

列出和检索：

```http
GET /api/v1/memories
GET /api/v1/memories?scope=profile
GET /api/v1/memories?query=输出
GET /api/v1/memories?enabled_only=false
```

更新记忆：

```http
PATCH /api/v1/memories/{memory_id}
Content-Type: application/json
```

```json
{
  "enabled": false,
  "value": "回答尽量短，但保留关键验证结果"
}
```

删除记忆：

```http
DELETE /api/v1/memories/{memory_id}
```

按 scope 清理：

```http
DELETE /api/v1/memories?scope=profile
```

## 审计与用户控制

记忆的 `enabled` 开关保存在 `metadata.enabled`。创建和更新会自动追加审计记录：

```json
{
  "audit": [
    {
      "action": "created",
      "actor_user_id": "user-1",
      "created_at": "2026-06-18T03:00:00+00:00"
    }
  ]
}
```

后续进入阶段 6 时，可以把这些审计记录扩展到独立审批和审计日志表。
