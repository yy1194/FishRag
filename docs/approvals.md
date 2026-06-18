# 阶段 6：人工审批与安全

当前已完成人工审批与医学安全基础闭环：

- HITL 审批队列。
- 高风险工具审批规则。
- Agent 工具调用前审批中断。
- 批准、拒绝、修改输入后返回可继续执行的 tool call。
- 审批审计记录。
- RAG 回答医学安全提示、免责声明和无证据高风险拦截。

## 审批队列

创建审批：

```http
POST /api/v1/approvals
Content-Type: application/json
```

```json
{
  "tool_name": "delete_document",
  "tool_input": {
    "document_id": "doc-1"
  },
  "reason": "删除知识库文档",
  "risk_level": "high",
  "categories": ["knowledge_base_mutation"]
}
```

列表和详情：

```http
GET /api/v1/approvals
GET /api/v1/approvals?status=pending
GET /api/v1/approvals/{approval_id}
```

审批或拒绝：

```http
POST /api/v1/approvals/{approval_id}/decision
Content-Type: application/json
```

```json
{
  "decision": "approved",
  "decision_reason": "只允许归档，不允许物理删除",
  "modified_tool_input": {
    "document_id": "doc-1",
    "mode": "archive"
  }
}
```

只有 `admin` 和 `reviewer` 可以审批。`member` 可以创建审批请求，但不能决定审批。

审批通过后响应会返回：

```json
{
  "resumable_tool_call": {
    "name": "delete_document",
    "arguments": {
      "document_id": "doc-1",
      "mode": "archive"
    }
  }
}
```

前端或 Agent 编排层可以用这个 `resumable_tool_call` 继续执行被审批后的工具调用。

## 审批审计

当前不新增数据库迁移，复用已有 `approvals.tool_input` JSON 存储：

- `original_tool_input`
- `approved_tool_input`
- `risk`
- `decision`
- `audit`

审计事件示例：

```json
{
  "action": "approved",
  "actor_user_id": "reviewer-1",
  "created_at": "2026-06-18T03:30:00+00:00"
}
```

## 默认高风险工具规则

默认需要审批的工具：

- `delete_document`
- `bulk_import_documents`
- `rebuild_index`
- `delete_vectors`
- `external_api_call`
- `file_write`
- `shell`
- `high_risk_medical_answer`

任意工具参数中如果显式传入：

```json
{
  "requires_approval": true
}
```

或：

```json
{
  "high_risk": true
}
```

也会触发审批。

## Agent 审批中断

`POST /api/v1/agent/sessions/{session_id}/run` 在执行工具前会使用审批策略检查工具调用。

如果命中高风险规则，Agent 不会执行该工具，而是返回：

```json
{
  "status": "waiting_for_approval",
  "tool_results": [
    {
      "name": "delete_document",
      "status": "approval_required",
      "output": {
        "approval_id": "approval-1",
        "approval_status": "pending"
      }
    }
  ]
}
```

同时会创建 `approvals` 记录，供审批中心处理。

## 医学安全

RAG 回答接口会进行确定性医学安全检查：

```http
POST /api/v1/rag/answer
```

当 query 或 answer 命中高风险医学词汇，例如诊断、处方、剂量、停药、换药、手术、急救等：

- 如果有 citation，会在回答末尾追加免责声明。
- 如果没有 citation，会拦截直接回答，把 `is_answered` 设置为 `false`。

响应会额外返回：

```json
{
  "safety": {
    "high_risk": true,
    "blocked": false,
    "reasons": ["Matched high-risk medical terms: 剂量."],
    "disclaimer": "..."
  }
}
```

当前安全检查是确定性 MVP，后续可以接入 `medical_reviewer` 子 Agent、专门审核模型或企业合规规则库。
