# 阶段 4：Agent 能力

当前已完成 Agent 能力基础闭环：

- 主 Agent 确定性运行时。
- 工具调用执行与结果记录。
- `write_todos` 规划工具接入。
- `rag_search` 知识库检索工具接入。
- 会话级记忆工具：`remember`、`recall_memory`。
- 子 Agent 注册和任务委托。
- 技能包元数据加载与按需加载。
- 上下文摘要和大工具结果压缩。

## 能力查询

```http
GET /api/v1/agent/tools
```

返回：

- `tools`：当前可用工具名。
- `subagents`：可委托的子 Agent 元数据。
- `skills`：可加载技能的元数据，不包含完整 instructions。

## Agent 运行接口

```http
POST /api/v1/agent/sessions/{session_id}/run
Content-Type: application/json
```

请求体示例：

```json
{
  "input": "请检索高血压相关证据，并记录下一步任务。",
  "tool_calls": [
    {
      "name": "write_todos",
      "arguments": {
        "todos": [
          {
            "id": "1",
            "content": "检索知识库证据",
            "status": "completed"
          }
        ]
      }
    },
    {
      "name": "rag_search",
      "arguments": {
        "query": "高血压诊疗建议",
        "limit": 5,
        "use_reranker": true
      }
    }
  ]
}
```

响应包含：

- `run_id`
- `session_id`
- `status`
- `response`
- `tool_results`
- `context`
- `available_tools`
- `available_subagents`
- `available_skills`

## 当前工具

### write_todos

替换式写入会话任务清单，复用 Planning 模块的 `InMemoryTodoStore`。

### rag_search

调用阶段 3 的混合检索链路，返回 hits 和 citations。该工具会使用 pgvector、OpenSearch 和可选 reranker。

### remember

写入会话级记忆：

```json
{
  "name": "remember",
  "arguments": {
    "key": "topic",
    "value": "高血压",
    "scope": "session"
  }
}
```

### recall_memory

读取会话级记忆，支持按 `scope` 和 `query` 过滤。

### task

委托一个或多个子 Agent：

```json
{
  "name": "task",
  "arguments": {
    "tasks": [
      {
        "subagent": "rag_researcher",
        "description": "整理检索证据",
        "input": "高血压诊疗建议"
      },
      {
        "subagent": "medical_reviewer",
        "description": "审核回答医学风险"
      }
    ]
  }
}
```

当前子 Agent 是确定性执行骨架，会记录输入、输出、工具范围和时间戳；后续可以替换为 LangGraph 子图或真实模型调用。

### list_skills

列出技能元数据，不加载完整 instructions。

### load_skill

按需加载某个技能包的完整 instructions：

```json
{
  "name": "load_skill",
  "arguments": {
    "name": "rag_answering"
  }
}
```

## 默认子 Agent

- `rag_researcher`：知识库检索、证据整理和引用提取。
- `document_processor`：文档解析、清洗、切片和索引检查。
- `medical_reviewer`：医学安全、证据覆盖和风险提示审核。
- `code_reviewer`：代码审查、回归风险和测试缺口检查。

## 默认技能

- `rag_answering`
- `document_ingestion`
- `medical_review`
- `task_planning`

## 上下文压缩

Agent 运行时会把用户输入、历史上下文和工具结果组织为 `ContextSnapshot`。当上下文条目数或字符数超过阈值时：

1. 保留最近上下文。
2. 将较早上下文压缩为摘要。
3. 对过大的工具输出保留 preview、原始长度和压缩标记。

该实现先保证可测试、可追踪，后续可以替换为模型摘要、数据库持久化和 LangGraph 状态管理。
