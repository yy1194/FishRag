# RAG 评估

阶段 8 的第一块已完成 RAG 离线评估基础能力。当前版本聚焦可复现的指标计算：调用方提交评测样本、标准相关 chunk、实际召回 chunk、回答引用 chunk，系统返回每条样本和整体聚合指标。

## API

```text
POST /api/v1/evaluations/rag/score
```

请求示例：

```json
{
  "ks": [1, 3, 5, 10],
  "examples": [
    {
      "id": "hypertension-guideline-001",
      "query": "高血压指南中的随访建议是什么？",
      "relevant_chunk_ids": ["chunk-guideline-1", "chunk-guideline-2"],
      "retrieved_chunk_ids": ["chunk-guideline-1", "chunk-other", "chunk-guideline-2"],
      "cited_chunk_ids": ["chunk-guideline-1"],
      "answer": "指南建议结合患者风险分层进行随访，并引用相关证据 [C1]。"
    }
  ]
}
```

响应包含：

- `ks`：实际参与计算的 k 值，自动去重、排序并过滤非正数。
- `aggregate`：全量样本的平均指标。
- `examples`：每条评测样本的指标明细。

## 批量评测任务

阶段 8 第二块新增评测任务 API，阶段 8 第三块已将任务持久化到 PostgreSQL，并补齐任务状态流转。当前后台执行使用 FastAPI 本地 `BackgroundTasks`，后续可以替换为 Celery/RQ。

### 创建任务

```text
POST /api/v1/evaluations/rag/jobs
```

离线评分模式：

```json
{
  "name": "Nightly RAG evaluation",
  "run_rag": false,
  "ks": [1, 3, 5, 10],
  "dataset_jsonl": "{\"id\":\"case-1\",\"query\":\"问题\",\"relevant_chunk_ids\":[\"chunk-a\"],\"retrieved_chunk_ids\":[\"chunk-a\"],\"cited_chunk_ids\":[\"chunk-a\"],\"answer\":\"回答 [C1]。\"}"
}
```

自动运行 RAG 模式：

```json
{
  "name": "Auto RAG evaluation",
  "run_rag": true,
  "run_in_background": false,
  "ks": [1, 3, 5],
  "limit": 10,
  "use_reranker": true,
  "examples": [
    {
      "id": "case-1",
      "query": "高血压指南中的随访建议是什么？",
      "relevant_chunk_ids": ["chunk-guideline-1", "chunk-guideline-2"]
    }
  ]
}
```

`run_rag=true` 时，系统会为每条样本调用现有 RAG 管线，自动生成：

- `retrieved_chunk_ids`
- `cited_chunk_ids`
- `answer`

随后再调用同一套指标计算逻辑生成评估报告。

`run_in_background=false` 时，接口会同步执行任务并返回最终状态。`run_in_background=true` 时，接口先返回 `queued` 状态，并由本地后台任务继续执行；客户端可以通过任务详情接口轮询最终报告。

### 查询任务列表

```text
GET /api/v1/evaluations/rag/jobs?limit=50
```

### 查询任务详情

```text
GET /api/v1/evaluations/rag/jobs/{job_id}
```

任务状态：

| 状态 | 说明 |
| --- | --- |
| `queued` | 任务已写入数据库，等待执行 |
| `running` | 任务正在执行 |
| `completed` | 任务已完成，`report` 中包含评估报告 |
| `failed` | 任务失败，`error` 中包含失败原因 |

任务模式：

| 模式 | 说明 |
| --- | --- |
| `scored_dataset` | 使用请求中已有的召回、引用和回答直接评分 |
| `auto_rag` | 自动调用 RAG 管线后评分 |

## JSONL 导入

`dataset_jsonl` 每一行是一条评测样本，字段与 `POST /api/v1/evaluations/rag/score` 中的 `examples` 一致。

示例：

```jsonl
{"id":"case-1","query":"问题 1","relevant_chunk_ids":["chunk-a"],"retrieved_chunk_ids":["chunk-a"],"cited_chunk_ids":["chunk-a"],"answer":"回答 [C1]。"}
{"id":"case-2","query":"问题 2","relevant_chunk_ids":[],"retrieved_chunk_ids":[],"cited_chunk_ids":[],"answer":""}
```

空行会被忽略。任意一行格式错误时，接口返回 `invalid_rag_evaluation_jsonl`，并在 `details.line` 中标记错误行号。

## 数据库存储

评测任务持久化在 `rag_evaluation_jobs` 表中，迁移文件为：

```text
migrations/versions/20260618_0002_rag_evaluation_jobs.py
```

核心字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 任务 ID |
| `owner_user_id` | 后续接入登录用户后的任务归属 |
| `name` | 任务名称 |
| `status` | `queued`、`running`、`completed`、`failed` |
| `mode` | `scored_dataset` 或 `auto_rag` |
| `ks` | 参与评估的 k 值 |
| `parameters` | 评测参数快照 |
| `examples` | 评测样本快照 |
| `report` | 完整评估报告 JSON |
| `error` | 失败原因 |
| `started_at` | 开始执行时间 |
| `completed_at` | 完成或失败时间 |

## 评测样本格式

| 字段 | 说明 |
| --- | --- |
| `id` | 样本 ID，用于定位失败案例 |
| `query` | 用户问题 |
| `relevant_chunk_ids` | 人工标注的标准相关 chunk |
| `retrieved_chunk_ids` | 系统实际召回结果，按排序顺序填写 |
| `cited_chunk_ids` | 回答中实际引用的 chunk |
| `answer` | 系统生成的回答文本 |

`retrieved_chunk_ids` 和 `cited_chunk_ids` 会按首次出现去重，避免重复 chunk 虚增指标。

## 指标定义

### recall@k

前 k 个召回结果命中的标准相关 chunk 数量，除以标准相关 chunk 总数。

### precision@k

前 k 个召回结果中标准相关 chunk 的占比。当前接口也返回该指标，便于排查召回结果是否掺入过多噪声。

### MRR

第一个标准相关 chunk 出现位置的倒数。如果第一个相关 chunk 排名第 2，则 MRR 为 `0.5`。

### nDCG@k

按二元相关性计算折损累计收益。越靠前命中标准相关 chunk，得分越高。

### citation coverage

回答引用命中的标准相关 chunk 数量，除以标准相关 chunk 总数。它衡量“该引用的证据是否覆盖了应该覆盖的证据”。

### faithfulness

当前版本使用确定性代理分，不调用模型裁判：

```text
supported_citations / cited_citations
```

其中 `supported_citations` 必须同时满足：

- 出现在回答引用中。
- 出现在召回结果中。
- 属于标准相关 chunk。

后续可以在此基础上增加模型裁判版 faithfulness，用于检查回答句子是否被引用内容逐句支撑。

## 不可回答样本

当 `relevant_chunk_ids` 为空时，表示该问题在知识库中无标准证据。

- 如果系统没有召回、没有引用、没有回答，则 recall、precision、MRR、nDCG、citation coverage 和 faithfulness 都记为 `1.0`。
- 如果系统召回或引用了无关证据，则相关指标会被扣分。

## 后续扩展

- 将 FastAPI 本地后台任务迁移到 Celery/RQ 后台队列。
- 为评测任务增加用户权限隔离、取消任务和重试任务。
- 增加模型裁判版 faithfulness、answer relevance 和 groundedness。
- 将评估指标接入前端评估面板和 Prometheus 监控。
