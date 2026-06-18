# 前端工作台说明

阶段 7 已完成 React 前端基础闭环，入口位于 `apps/web`。当前界面不是营销页，而是面向医学知识库日常操作的工作台，覆盖登录、会话问答、文档入库、Agent 任务、人工审批和评估概览。

## 技术栈

- React 19
- TypeScript
- Vite
- Tailwind CSS
- lucide-react
- ESLint

## 运行方式

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
```

默认开发地址：

```text
http://127.0.0.1:5173
```

如果后端不是默认地址，在 `apps/web/.env.local` 中配置：

```text
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

## 页面能力

### 登录

- 登录表单会调用 `POST /api/v1/auth/login`。
- 在后端未启动或账号不可用时，前端会进入本地演示模式，便于继续查看界面和交互。
- 登录态目前保存在组件状态中，后续阶段可扩展为持久化 token、刷新 token 和权限菜单。

### 聊天与引用

- 左侧展示会话列表，支持新建本地会话。
- 中间区域展示用户消息、助手回答和引用标记。
- 发送问题时优先调用 `POST /api/v1/rag/answer`。
- 接口不可用时使用本地演示回答，并保留医学安全免责声明。

### 文档入库

- 文档页展示上传、解析、索引状态和 chunk 数量。
- 上传文件优先调用 `POST /api/v1/documents/upload`。
- 上传失败或后端未启动时，前端会创建本地演示记录，状态显示为 `uploaded`。

### Agent 任务

- 任务页展示 `pending`、`in_progress`、`completed`、`blocked` 状态。
- 点击运行后会创建本地任务流，并尝试调用 `POST /api/v1/agent/sessions/{session_id}/run`。
- 高风险动作会同步写入审批中心的待审批项，模拟 HITL 中断体验。

### 审批中心

- 展示待审批、已批准、已拒绝的工具调用。
- 支持批准和拒绝操作。
- 当前按钮先更新本地状态，后续可继续接入 `POST /api/v1/approvals/{approval_id}/decide`。

### RAG 评估

- 展示 recall@k、MRR、faithfulness、citation coverage 等评估指标。
- 展示召回链路健康度和质量检查项。
- 当前为静态评估面板，阶段 8 会接入真实评测任务和指标统计。

## 验证命令

```bash
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

当前已通过 ESLint 与生产构建验证。

## 后续扩展

- 将会话、消息、文档和审批数据全部切换为真实后端列表接口。
- 增加 token 持久化、登出清理和 401 自动处理。
- 为文档入库增加解析进度轮询。
- 为 Agent 运行增加事件流展示。
- 在阶段 8 接入真实 RAG 评估任务、Playwright 端到端测试和可观测性面板。
