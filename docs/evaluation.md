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

- 接入真实批量 RAG 运行，自动生成 `retrieved_chunk_ids`、`cited_chunk_ids` 和 `answer`。
- 支持从 JSONL 文件导入评测集。
- 增加评测任务表、任务状态和历史报告。
- 增加模型裁判版 faithfulness、answer relevance 和 groundedness。
- 将评估指标接入前端评估面板和 Prometheus 监控。
