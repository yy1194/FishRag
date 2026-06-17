# 阶段 2：文档上传

当前已完成文档入库 MVP 的第一小块：

- 文档上传 API。
- 上传文件安全落盘。
- `documents` 记录创建。
- 文档状态基础流转。

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
