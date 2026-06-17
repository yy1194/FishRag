# 阶段 2：文档上传、解析、切片与索引

当前已完成文档入库 MVP 的基础闭环：

- 文档上传 API。
- 上传文件安全落盘。
- `documents` 记录创建。
- 文档状态基础流转。
- TXT、Markdown、CSV、DOCX 解析适配层。
- 文档解析预览 API。
- 文本清洗、章节识别和 chunk 入库 API。
- OpenAI-compatible Embedding 适配层。
- chunk 向量写入 API。
- OpenSearch 关键词索引适配层。
- chunk 文本与元数据写入关键词索引 API。

## 上传接口

```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data
```

表单字段：

- `file`：必填，上传的原始文件。
- `metadata`：可选，JSON object 字符串，用于保存来源、分类等自定义元数据。

响应会返回：

- `id`：文档 ID。
- `filename`：安全化后的文件名。
- `content_type`：上传文件 MIME 类型。
- `status`：初始状态为 `uploaded`。
- `checksum`：SHA-256 文件校验值。
- `storage_path`：相对 `FISHRAG_UPLOAD_DIR` 的落盘路径。
- `metadata`：上传元数据，包括文件大小、原始文件名和自定义元数据。

## 落盘路径规范

物理路径：

```text
<FISHRAG_UPLOAD_DIR>/<yyyy>/<mm>/<dd>/<document_id>/<safe_filename>
```

默认配置：

```text
FISHRAG_UPLOAD_DIR=storage/uploads
FISHRAG_MAX_UPLOAD_BYTES=52428800
```

数据库中的 `documents.storage_path` 只保存相对路径：

```text
2026/06/17/<document_id>/<safe_filename>
```

这样后续迁移存储目录、对象存储或容器挂载路径时，不需要改历史记录。

## 解析接口

```http
POST /api/v1/documents/{document_id}/parse
```

查询参数：

- `preview_chars`：可选，返回的文本预览长度，默认 `2000`，最大 `20000`。

响应会返回：

- `document_id`：文档 ID。
- `status`：解析成功后推进到 `processing`。
- `source_type`：解析出的文档类型。
- `parser`：使用的解析器名称。
- `text_preview`：解析文本预览。
- `text_length`：完整解析文本长度。
- `metadata`：解析元数据。

已支持格式：

- TXT：支持 `utf-8-sig`、`utf-8`、`gb18030` 编码兜底。
- Markdown：保留正文文本，识别 `#` 到 `######` 标题结构。
- CSV：使用标准库读取，并转换为适合 RAG 的行文本。
- DOCX：使用 zip/xml 读取 `word/document.xml` 中的段落文本。
- PDF：使用 PyMuPDF 提取页面文本。

PDF 解析依赖 `pymupdf` 已作为正式项目依赖接入，并通过真实 PDF 解析和 API 解析链路测试。

## 切片接口

```http
POST /api/v1/documents/{document_id}/chunks
Content-Type: application/json
```

请求体：

```json
{
  "max_chars": 1200,
  "overlap_chars": 150
}
```

处理流程：

1. 读取 `documents.storage_path` 指向的落盘文件。
2. 使用解析适配层提取文本。
3. 清洗文本：统一换行、去除 BOM、去除行尾空白、合并多余空行、修复英文断行连字符。
4. 识别章节：支持 Markdown 标题和常见编号标题。
5. 调用 chunk 切分器生成 chunk。
6. 替换写入 `document_chunks` 表。
7. 将文档状态推进到 `processing`。

每个 chunk 会保存：

- `document_id`
- `chunk_index`
- `content`
- `token_count`：基于字符的粗估 token 数。
- `metadata.start` / `metadata.end`：chunk 在清洗后文本中的字符范围。
- `metadata.section_title`
- `metadata.section_level`
- `metadata.section_path`
- `metadata.source_type`
- `metadata.parser`

响应会返回 chunk 数量、章节数量和 chunk 预览。

## 向量化接口

```http
POST /api/v1/documents/{document_id}/embeddings
Content-Type: application/json
```

请求体：

```json
{
  "batch_size": 16,
  "overwrite": false
}
```

处理流程：

1. 查询指定文档的 `document_chunks`。
2. 默认跳过已经有 `embedding` 的 chunk。
3. 按 `batch_size` 调用 OpenAI-compatible Embedding API。
4. 将向量写回 `document_chunks.embedding`。
5. 在 chunk 元数据中记录 embedding provider、model 和 dimensions。
6. 在文档元数据中记录本次向量化摘要。

默认模型配置：

```text
FISHRAG_EMBEDDING_PROVIDER=siliconflow
FISHRAG_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
FISHRAG_EMBEDDING_MODEL=BAAI/bge-m3
FISHRAG_EMBEDDING_DIMENSIONS=1024
```

当前实现不会在测试中调用真实云端接口；单元测试使用 mock client 和 mock transport 验证请求、响应解析和向量写入逻辑。

## 关键词索引接口

```http
POST /api/v1/documents/{document_id}/keyword-index
Content-Type: application/json
```

请求体：

```json
{
  "refresh": false
}
```

处理流程：

1. 查询指定文档的 `document_chunks`。
2. 确保 OpenSearch index 存在。
3. 将 chunk content 和元数据转换为 OpenSearch 文档。
4. 使用 OpenSearch Bulk API 写入。
5. 成功后将 `documents.status` 推进到 `indexed`。

默认索引配置：

```text
FISHRAG_OPENSEARCH_URL=http://localhost:9200
FISHRAG_OPENSEARCH_INDEX_NAME=fishrag_chunks
```

索引文档会包含：

- `document_id`
- `chunk_id`
- `chunk_index`
- `content`
- `metadata.filename`
- `metadata.content_type`
- `metadata.section_title`
- `metadata.section_path`
- `metadata.source_type`
- `metadata.parser`
- `metadata.token_count`

如果 OpenSearch Bulk API 返回部分错误，接口会返回 `error_count` 和 `errors`，但不会把文档状态标记为 `indexed`。

## 状态流转

当前支持状态：

- `uploaded`：文件已上传并完成落盘。
- `processing`：解析、清洗、切片或索引处理中。
- `indexed`：完成入库和索引。
- `failed`：处理失败。

允许的流转：

```text
uploaded -> processing
uploaded -> failed
processing -> indexed
processing -> failed
indexed -> processing
failed -> processing
```

状态更新接口：

```http
PATCH /api/v1/documents/{document_id}/status
Content-Type: application/json
```

示例：

```json
{
  "status": "processing"
}
```

失败状态可以携带错误信息：

```json
{
  "status": "failed",
  "error_message": "PDF parser failed."
}
```
