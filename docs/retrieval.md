# 阶段 3：RAG 检索与回答

当前已完成 RAG 检索与回答的基础闭环：

- pgvector 向量检索。
- OpenSearch BM25 关键词检索。
- Reciprocal Rank Fusion 多路召回融合。
- OpenAI-compatible reranker 重排。
- `rag_search` 查询结果封装。
- 带引用的回答生成。
- 无证据回答策略。

## 检索接口

### 向量检索

```http
POST /api/v1/rag/vector-search
Content-Type: application/json
```

请求体：

```json
{
  "query": "高血压诊疗建议是什么？",
  "limit": 10
}
```

处理流程：

1. 使用 Embedding 模型对 query 向量化。
2. 使用 `document_chunks.embedding <=> query_vector` 在 pgvector 中排序。
3. 返回 chunk、来源元数据和 citation。

### 关键词检索

```http
POST /api/v1/rag/keyword-search
Content-Type: application/json
```

请求体：

```json
{
  "query": "高血压 禁忌症",
  "limit": 10
}
```

处理流程：

1. 查询 OpenSearch index。
2. 使用 `multi_match` 同时检索 `content`、`metadata.section_title` 和 `metadata.section_path`。
3. 返回 BM25 score、chunk 文本和来源元数据。

### 混合检索

```http
POST /api/v1/rag/hybrid-search
Content-Type: application/json
```

请求体：

```json
{
  "query": "高血压患者用药注意事项",
  "vector_limit": 20,
  "keyword_limit": 20,
  "limit": 10,
  "use_reranker": true,
  "reranker_top_n": 10
}
```

处理流程：

1. 并行执行向量检索和关键词检索。
2. 使用 RRF 融合候选片段。
3. 可选调用 reranker 对融合结果重排。
4. 生成稳定 citation 编号。

### RAG 查询工具

```http
POST /api/v1/rag/search
Content-Type: application/json
```

该接口与混合检索使用同一套参数，是后续 Agent 工具 `rag_search` 的 HTTP 入口。返回结构包括：

- `query`
- `hits`
- `citations`

每条 citation 会包含：

- `id`：例如 `C1`。
- `document_id`
- `chunk_id`
- `chunk_index`
- `content`
- `score`
- `source`
- `metadata`

## 回答接口

```http
POST /api/v1/rag/answer
Content-Type: application/json
```

请求体：

```json
{
  "query": "高血压患者需要注意哪些用药事项？",
  "vector_limit": 20,
  "keyword_limit": 20,
  "limit": 5,
  "use_reranker": true,
  "reranker_top_n": 10
}
```

处理流程：

1. 执行混合检索。
2. 构造 `[C1] ...` 格式证据上下文。
3. 调用 Chat 模型生成回答。
4. 返回回答文本和引用列表。

如果没有检索到证据，接口会直接返回无证据回答，不调用 Chat 模型，避免把模型猜测伪装成知识库依据。

## 模型配置

Chat、Embedding、Reranker 三条调用链互相独立：

```text
FISHRAG_LLM_BASE_URL=https://api.deepseek.com
FISHRAG_CHAT_MODEL=deepseek-v4-flash
FISHRAG_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
FISHRAG_EMBEDDING_MODEL=BAAI/bge-m3
FISHRAG_RERANKER_BASE_URL=https://api.siliconflow.cn/v1
FISHRAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

## 测试覆盖

阶段 3 已补充以下测试：

- RRF 融合、citation 构建、无证据回答策略。
- OpenSearch 关键词搜索响应解析。
- Reranker 请求、响应解析和异常索引处理。
- Chat completions 请求与回答生成上下文。
- RAG API 混合检索和无证据回答闭环。
