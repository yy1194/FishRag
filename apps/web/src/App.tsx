import {
  Activity,
  Archive,
  BarChart3,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileText,
  FileUp,
  KeyRound,
  ListTodo,
  LogOut,
  MessageSquareText,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Upload,
  UserRound,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { type FormEvent, type RefObject, useMemo, useRef, useState } from "react";

type View = "chat" | "documents" | "tasks" | "approvals" | "evaluation";
type DocumentStatus = "uploaded" | "processing" | "indexed" | "failed";
type TodoStatus = "pending" | "in_progress" | "completed" | "blocked";
type ApprovalStatus = "pending" | "approved" | "rejected";

type SessionItem = {
  id: string;
  title: string;
  status: "active" | "archived";
  updatedAt: string;
};

type Citation = {
  id: string;
  title: string;
  meta: string;
  content: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

type KnowledgeDocument = {
  id: string;
  name: string;
  type: string;
  status: DocumentStatus;
  chunks: number;
  updatedAt: string;
};

type Todo = {
  id: string;
  content: string;
  status: TodoStatus;
};

type ApprovalItem = {
  id: string;
  tool: string;
  status: ApprovalStatus;
  risk: string;
  requester: string;
  createdAt: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

const sessionsSeed: SessionItem[] = [
  { id: "session-guideline", title: "医学指南问答", status: "active", updatedAt: "09:42" },
  { id: "session-ingestion", title: "知识库入库检查", status: "active", updatedAt: "昨天" },
  { id: "session-eval", title: "RAG 评估任务", status: "archived", updatedAt: "周一" },
];

const citationsSeed: Citation[] = [
  {
    id: "C1",
    title: "高血压基层诊疗指南",
    meta: "PDF · 第 12 页 · chunk-0042",
    content: "治疗方案需要结合风险分层、合并症和禁忌证，并保留随访记录。",
  },
  {
    id: "C2",
    title: "药品不良反应处理 SOP",
    meta: "DOCX · 第 3 节 · chunk-0017",
    content: "出现不良反应时应记录用药时间、剂量、症状和处理结果。",
  },
  {
    id: "C3",
    title: "内部培训 FAQ",
    meta: "MD · 问答条目 · chunk-0008",
    content: "知识库回答需要展示引用来源，并提示不能替代医生判断。",
  },
];

const messagesSeed: Message[] = [
  {
    id: "m1",
    role: "user",
    content: "请查询高血压患者用药注意事项，并标注知识库来源。",
  },
  {
    id: "m2",
    role: "assistant",
    content:
      "知识库提示，高血压患者用药需要结合风险分层、合并症、禁忌证和不良反应记录。[C1][C2]\n\n本回答仅用于知识库资料辅助阅读，不能替代医生诊断、治疗建议或监管要求。",
    citations: citationsSeed.slice(0, 2),
  },
];

const documentsSeed: KnowledgeDocument[] = [
  {
    id: "doc-001",
    name: "高血压基层诊疗指南.pdf",
    type: "PDF",
    status: "indexed",
    chunks: 86,
    updatedAt: "今天 09:30",
  },
  {
    id: "doc-002",
    name: "药品不良反应处理 SOP.docx",
    type: "DOCX",
    status: "processing",
    chunks: 31,
    updatedAt: "今天 08:50",
  },
  {
    id: "doc-003",
    name: "内部培训 FAQ.md",
    type: "Markdown",
    status: "indexed",
    chunks: 18,
    updatedAt: "昨天",
  },
];

const todosSeed: Todo[] = [
  { id: "1", content: "检索高血压用药证据", status: "completed" },
  { id: "2", content: "检查引用覆盖率", status: "in_progress" },
  { id: "3", content: "提交医学安全复核", status: "pending" },
];

const approvalsSeed: ApprovalItem[] = [
  {
    id: "apv-001",
    tool: "high_risk_medical_answer",
    status: "pending",
    risk: "critical",
    requester: "member",
    createdAt: "10:12",
  },
  {
    id: "apv-002",
    tool: "delete_document",
    status: "approved",
    risk: "high",
    requester: "admin",
    createdAt: "昨天",
  },
  {
    id: "apv-003",
    tool: "shell",
    status: "rejected",
    risk: "critical",
    requester: "member",
    createdAt: "周一",
  },
];

const viewItems: Array<{ id: View; label: string; icon: LucideIcon }> = [
  { id: "chat", label: "问答", icon: MessageSquareText },
  { id: "documents", label: "文档", icon: FileText },
  { id: "tasks", label: "任务", icon: ListTodo },
  { id: "approvals", label: "审批", icon: ClipboardCheck },
  { id: "evaluation", label: "评估", icon: BarChart3 },
];

const statusText: Record<DocumentStatus, string> = {
  uploaded: "已上传",
  processing: "处理中",
  indexed: "已索引",
  failed: "失败",
};

const todoText: Record<TodoStatus, string> = {
  pending: "待处理",
  in_progress: "进行中",
  completed: "已完成",
  blocked: "阻塞",
};

const approvalText: Record<ApprovalStatus, string> = {
  pending: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
};

export function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("demo@fishrag.local");
  const [password, setPassword] = useState("demo-password");
  const [view, setView] = useState<View>("chat");
  const [activeSessionId, setActiveSessionId] = useState(sessionsSeed[0].id);
  const [sessions, setSessions] = useState(sessionsSeed);
  const [messages, setMessages] = useState(messagesSeed);
  const [documents, setDocuments] = useState(documentsSeed);
  const [todos, setTodos] = useState(todosSeed);
  const [approvals, setApprovals] = useState(approvalsSeed);
  const [prompt, setPrompt] = useState("");
  const [systemState, setSystemState] = useState("本地演示");
  const [isBusy, setIsBusy] = useState(false);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0];
  const indexedDocuments = documents.filter((document) => document.status === "indexed").length;
  const pendingApprovals = approvals.filter((approval) => approval.status === "pending").length;
  const completedTodos = todos.filter((todo) => todo.status === "completed").length;

  const latestCitations = useMemo(
    () => messages.flatMap((message) => message.citations ?? []).slice(-4),
    [messages],
  );

  async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    try {
      const result = await apiRequest<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(result.access_token);
      setSystemState("已连接 API");
    } catch {
      setToken("local-demo-token");
      setSystemState("本地演示");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question) {
      return;
    }
    setPrompt("");
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: question },
    ]);
    setIsBusy(true);
    try {
      const answer = await apiRequest<{
        answer: string;
        citations: Array<{
          id: string;
          metadata: Record<string, unknown>;
          content: string;
        }>;
      }>("/rag/answer", {
        method: "POST",
        body: JSON.stringify({ query: question, limit: 5, use_reranker: true }),
      });
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: answer.answer,
          citations: answer.citations.map((citation) => ({
            id: citation.id,
            title: String(citation.metadata.filename ?? "知识库片段"),
            meta: String(citation.metadata.section_title ?? citation.metadata.storage_path ?? "chunk"),
            content: citation.content,
          })),
        },
      ]);
      setSystemState("已连接 API");
    } catch {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            "已根据本地演示知识库整理回答：请优先查看指南证据，并在涉及剂量、停药、换药时提交医学安全复核。[C1][C3]\n\n本回答仅用于知识库资料辅助阅读，不能替代医生诊断、治疗建议或监管要求。",
          citations: [citationsSeed[0], citationsSeed[2]],
        },
      ]);
      setSystemState("本地演示");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(file: File | null) {
    if (!file) {
      return;
    }
    const nextDocument: KnowledgeDocument = {
      id: crypto.randomUUID(),
      name: file.name,
      type: file.name.split(".").pop()?.toUpperCase() ?? "FILE",
      status: "uploaded",
      chunks: 0,
      updatedAt: "刚刚",
    };
    setDocuments((current) => [nextDocument, ...current]);
    if (!token) {
      return;
    }
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${apiBaseUrl}/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body,
      });
      if (response.ok) {
        setSystemState("已连接 API");
      }
    } catch {
      setSystemState("本地演示");
    }
  }

  async function runAgentTask() {
    setIsBusy(true);
    setTodos((current) =>
      current.map((todo) => (todo.id === "2" ? { ...todo, status: "completed" } : todo)),
    );
    setApprovals((current) => [
      {
        id: `apv-${current.length + 1}`.padStart(7, "0"),
        tool: "high_risk_medical_answer",
        status: "pending",
        risk: "critical",
        requester: "agent",
        createdAt: "刚刚",
      },
      ...current,
    ]);
    try {
      await apiRequest(`/agent/sessions/${activeSession.id}/run`, {
        method: "POST",
        body: JSON.stringify({
          input: "执行当前问答任务",
          tool_calls: [
            {
              name: "write_todos",
              arguments: { todos },
            },
          ],
        }),
      });
      setSystemState("已连接 API");
    } catch {
      setSystemState("本地演示");
    } finally {
      setIsBusy(false);
    }
  }

  function decideApproval(id: string, status: ApprovalStatus) {
    setApprovals((current) =>
      current.map((approval) => (approval.id === id ? { ...approval, status } : approval)),
    );
  }

  function createSession() {
    const next: SessionItem = {
      id: crypto.randomUUID(),
      title: "新的会话",
      status: "active",
      updatedAt: "刚刚",
    };
    setSessions((current) => [next, ...current]);
    setActiveSessionId(next.id);
    setMessages([]);
    setView("chat");
  }

  if (!token) {
    return (
      <main className="grid min-h-screen place-items-center bg-zinc-100 px-4 py-8 text-zinc-950">
        <form
          className="w-full max-w-sm rounded-md border border-zinc-200 bg-white p-5 shadow-sm"
          onSubmit={handleLogin}
        >
          <div className="mb-5 flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md bg-teal-700 text-white">
              <Bot size={21} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">FishRag</h1>
              <p className="text-sm text-zinc-500">医学知识库工作台</p>
            </div>
          </div>
          <label className="mb-3 block text-sm font-medium text-zinc-700" htmlFor="email">
            邮箱
          </label>
          <div className="mb-4 flex h-11 items-center gap-2 rounded-md border border-zinc-300 px-3">
            <UserRound size={17} className="text-zinc-500" />
            <input
              className="min-w-0 flex-1 border-0 text-sm outline-none"
              id="email"
              onChange={(event) => setEmail(event.target.value)}
              value={email}
            />
          </div>
          <label className="mb-3 block text-sm font-medium text-zinc-700" htmlFor="password">
            密码
          </label>
          <div className="mb-5 flex h-11 items-center gap-2 rounded-md border border-zinc-300 px-3">
            <KeyRound size={17} className="text-zinc-500" />
            <input
              className="min-w-0 flex-1 border-0 text-sm outline-none"
              id="password"
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
          </div>
          <button
            className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white disabled:opacity-60"
            disabled={isBusy}
            type="submit"
          >
            <ShieldCheck size={17} />
            登录
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[264px_minmax(0,1fr)]">
        <aside className="border-b border-zinc-200 bg-white lg:border-b-0 lg:border-r">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-md bg-teal-700 text-white">
                <Bot size={21} />
              </div>
              <div>
                <h1 className="text-base font-semibold">FishRag</h1>
                <p className="text-xs text-zinc-500">{systemState}</p>
              </div>
            </div>
            <button
              aria-label="退出登录"
              className="grid h-9 w-9 place-items-center rounded-md text-zinc-500 hover:bg-zinc-100"
              onClick={() => setToken("")}
            >
              <LogOut size={18} />
            </button>
          </div>
          <div className="grid grid-cols-5 gap-1 border-t border-zinc-100 px-2 py-2 lg:grid-cols-1 lg:border-t-0 lg:px-3">
            {viewItems.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  className={`flex h-10 items-center justify-center gap-2 rounded-md px-2 text-sm lg:justify-start ${
                    view === item.id
                      ? "bg-teal-50 text-teal-800"
                      : "text-zinc-600 hover:bg-zinc-100"
                  }`}
                  key={item.id}
                  onClick={() => setView(item.id)}
                >
                  <Icon size={17} />
                  <span className="hidden lg:inline">{item.label}</span>
                </button>
              );
            })}
          </div>
          <div className="hidden border-t border-zinc-100 px-3 py-4 lg:block">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-zinc-500">会话</span>
              <button
                aria-label="新建会话"
                className="grid h-8 w-8 place-items-center rounded-md text-zinc-600 hover:bg-zinc-100"
                onClick={createSession}
              >
                <MessageSquareText size={17} />
              </button>
            </div>
            <div className="space-y-1">
              {sessions.map((session) => (
                <button
                  className={`h-12 w-full rounded-md px-3 text-left ${
                    activeSessionId === session.id
                      ? "bg-zinc-900 text-white"
                      : "text-zinc-700 hover:bg-zinc-100"
                  }`}
                  key={session.id}
                  onClick={() => setActiveSessionId(session.id)}
                >
                  <span className="block truncate text-sm font-medium">{session.title}</span>
                  <span className="block text-xs opacity-70">{session.updatedAt}</span>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <section className="flex min-w-0 flex-col">
          <header className="flex min-h-16 flex-col justify-center gap-3 border-b border-zinc-200 bg-white px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-base font-semibold">{headerTitle(view, activeSession.title)}</h2>
              <p className="text-sm text-zinc-500">{indexedDocuments} 份已索引文档</p>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:flex">
              <MetricPill icon={Database} label="文档" value={String(documents.length)} />
              <MetricPill icon={ListTodo} label="任务" value={`${completedTodos}/${todos.length}`} />
              <MetricPill icon={ShieldCheck} label="审批" value={String(pendingApprovals)} />
            </div>
          </header>

          {view === "chat" && (
            <ChatView
              citations={latestCitations}
              isBusy={isBusy}
              messages={messages}
              onPromptChange={setPrompt}
              onSend={handleSend}
              prompt={prompt}
            />
          )}
          {view === "documents" && (
            <DocumentsView
              documents={documents}
              fileInputRef={fileInputRef}
              onPickFile={() => fileInputRef.current?.click()}
              onUpload={handleUpload}
            />
          )}
          {view === "tasks" && (
            <TasksView isBusy={isBusy} onRunAgent={runAgentTask} todos={todos} />
          )}
          {view === "approvals" && (
            <ApprovalsView approvals={approvals} onDecision={decideApproval} />
          )}
          {view === "evaluation" && <EvaluationView />}
        </section>
      </div>
    </main>
  );
}

function MetricPill({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex h-10 min-w-24 items-center gap-2 rounded-md border border-zinc-200 bg-zinc-50 px-3">
      <Icon size={16} className="text-teal-700" />
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="ml-auto text-sm font-semibold">{value}</span>
    </div>
  );
}

function ChatView({
  citations,
  isBusy,
  messages,
  onPromptChange,
  onSend,
  prompt,
}: {
  citations: Citation[];
  isBusy: boolean;
  messages: Message[];
  onPromptChange: (value: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  prompt: string;
}) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-h-0 flex-col">
        <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-5 md:px-6">
          {messages.map((message) => (
            <article
              className={`max-w-3xl rounded-md border p-4 ${
                message.role === "assistant"
                  ? "border-teal-100 bg-teal-50"
                  : "border-zinc-200 bg-white"
              }`}
              key={message.id}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                {message.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}
                {message.role === "assistant" ? "FishRag" : "用户"}
              </div>
              <p className="whitespace-pre-line text-sm leading-6 text-zinc-800">{message.content}</p>
              {message.citations && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {message.citations.map((citation) => (
                    <span
                      className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800"
                      key={citation.id}
                    >
                      {citation.id} · {citation.title}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
        <form className="border-t border-zinc-200 bg-white p-4" onSubmit={onSend}>
          <div className="flex items-end gap-3 rounded-md border border-zinc-300 bg-white p-3">
            <textarea
              className="min-h-12 flex-1 resize-none border-0 text-sm outline-none"
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder="输入医学知识库问题..."
              value={prompt}
            />
            <button
              aria-label="发送"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-teal-700 text-white disabled:opacity-60"
              disabled={isBusy}
              type="submit"
            >
              <Send size={18} />
            </button>
          </div>
        </form>
      </div>
      <EvidencePanel citations={citations.length ? citations : citationsSeed} />
    </div>
  );
}

function EvidencePanel({ citations }: { citations: Citation[] }) {
  return (
    <aside className="hidden border-l border-zinc-200 bg-white px-5 py-5 xl:block">
      <div className="mb-4 flex items-center gap-2">
        <Database size={18} className="text-teal-700" />
        <h3 className="text-base font-semibold">证据片段</h3>
      </div>
      <div className="space-y-3">
        {citations.map((citation) => (
          <div className="rounded-md border border-zinc-200 p-4" key={`${citation.id}-${citation.meta}`}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="truncate text-sm font-semibold">{citation.title}</h4>
              <span className="rounded-md bg-amber-100 px-2 py-1 text-xs text-amber-800">
                {citation.id}
              </span>
            </div>
            <p className="mb-2 text-xs text-zinc-500">{citation.meta}</p>
            <p className="text-sm leading-6 text-zinc-700">{citation.content}</p>
          </div>
        ))}
      </div>
    </aside>
  );
}

function DocumentsView({
  documents,
  fileInputRef,
  onPickFile,
  onUpload,
}: {
  documents: KnowledgeDocument[];
  fileInputRef: RefObject<HTMLInputElement | null>;
  onPickFile: () => void;
  onUpload: (file: File | null) => void;
}) {
  return (
    <div className="flex-1 overflow-auto px-4 py-5 md:px-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <FileUp size={18} className="text-teal-700" />
          <h3 className="text-base font-semibold">文档入库</h3>
        </div>
        <input
          className="hidden"
          onChange={(event) => onUpload(event.target.files?.[0] ?? null)}
          ref={fileInputRef}
          type="file"
        />
        <button
          className="flex h-10 items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white"
          onClick={onPickFile}
          type="button"
        >
          <Upload size={17} />
          上传
        </button>
      </div>
      <div className="overflow-hidden rounded-md border border-zinc-200 bg-white">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-zinc-50 text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-3">文件</th>
              <th className="hidden px-4 py-3 sm:table-cell">类型</th>
              <th className="px-4 py-3">状态</th>
              <th className="hidden px-4 py-3 md:table-cell">Chunks</th>
              <th className="hidden px-4 py-3 lg:table-cell">更新</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {documents.map((document) => (
              <tr key={document.id}>
                <td className="truncate px-4 py-4 font-medium">{document.name}</td>
                <td className="hidden px-4 py-4 text-zinc-600 sm:table-cell">{document.type}</td>
                <td className="px-4 py-4">
                  <StatusBadge status={document.status} />
                </td>
                <td className="hidden px-4 py-4 text-zinc-600 md:table-cell">{document.chunks}</td>
                <td className="hidden px-4 py-4 text-zinc-600 lg:table-cell">{document.updatedAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TasksView({
  isBusy,
  onRunAgent,
  todos,
}: {
  isBusy: boolean;
  onRunAgent: () => void;
  todos: Todo[];
}) {
  return (
    <div className="grid flex-1 grid-cols-1 gap-4 overflow-auto px-4 py-5 md:grid-cols-[minmax(0,1fr)_320px] md:px-6">
      <section className="rounded-md border border-zinc-200 bg-white">
        <div className="flex min-h-14 items-center justify-between border-b border-zinc-100 px-4">
          <h3 className="text-base font-semibold">任务清单</h3>
          <button
            className="flex h-9 items-center gap-2 rounded-md bg-indigo-700 px-3 text-sm font-semibold text-white disabled:opacity-60"
            disabled={isBusy}
            onClick={onRunAgent}
            type="button"
          >
            <Activity size={16} />
            运行
          </button>
        </div>
        <div className="divide-y divide-zinc-100">
          {todos.map((todo) => (
            <div className="flex min-h-14 items-center gap-3 px-4" key={todo.id}>
              <TodoIcon status={todo.status} />
              <span className="min-w-0 flex-1 truncate text-sm">{todo.content}</span>
              <span className="text-xs text-zinc-500">{todoText[todo.status]}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-md border border-zinc-200 bg-white p-4">
        <div className="mb-4 flex items-center gap-2">
          <Bot size={18} className="text-indigo-700" />
          <h3 className="text-base font-semibold">Agent 状态</h3>
        </div>
        <div className="space-y-3 text-sm">
          <StateRow label="Runtime" value="ready" />
          <StateRow label="RAG Tool" value="enabled" />
          <StateRow label="HITL" value="watching" />
          <StateRow label="Memory" value="session" />
        </div>
      </section>
    </div>
  );
}

function ApprovalsView({
  approvals,
  onDecision,
}: {
  approvals: ApprovalItem[];
  onDecision: (id: string, status: ApprovalStatus) => void;
}) {
  return (
    <div className="flex-1 overflow-auto px-4 py-5 md:px-6">
      <div className="grid gap-3 md:grid-cols-3">
        {approvals.map((approval) => (
          <article className="rounded-md border border-zinc-200 bg-white p-4" key={approval.id}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="truncate text-sm font-semibold">{approval.tool}</h3>
              <ApprovalBadge status={approval.status} />
            </div>
            <div className="space-y-2 text-sm text-zinc-600">
              <StateRow label="风险" value={approval.risk} />
              <StateRow label="申请人" value={approval.requester} />
              <StateRow label="时间" value={approval.createdAt} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button
                className="flex h-9 items-center justify-center gap-2 rounded-md bg-emerald-700 px-3 text-sm font-semibold text-white disabled:opacity-50"
                disabled={approval.status !== "pending"}
                onClick={() => onDecision(approval.id, "approved")}
                type="button"
              >
                <CheckCircle2 size={16} />
                批准
              </button>
              <button
                className="flex h-9 items-center justify-center gap-2 rounded-md bg-rose-700 px-3 text-sm font-semibold text-white disabled:opacity-50"
                disabled={approval.status !== "pending"}
                onClick={() => onDecision(approval.id, "rejected")}
                type="button"
              >
                <XCircle size={16} />
                拒绝
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function EvaluationView() {
  const metrics = [
    { label: "Recall@5", value: "0.82", delta: "+0.04" },
    { label: "MRR", value: "0.68", delta: "+0.02" },
    { label: "nDCG", value: "0.74", delta: "+0.01" },
    { label: "Citation", value: "0.91", delta: "+0.05" },
  ];
  return (
    <div className="flex-1 overflow-auto px-4 py-5 md:px-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-indigo-700" />
          <h3 className="text-base font-semibold">RAG 评估</h3>
        </div>
        <button className="grid h-9 w-9 place-items-center rounded-md border border-zinc-300 bg-white text-zinc-600">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        {metrics.map((metric) => (
          <div className="rounded-md border border-zinc-200 bg-white p-4" key={metric.label}>
            <p className="text-xs text-zinc-500">{metric.label}</p>
            <div className="mt-3 flex items-end justify-between">
              <span className="text-2xl font-semibold">{metric.value}</span>
              <span className="text-sm text-emerald-700">{metric.delta}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-md border border-zinc-200 bg-white p-4">
        <div className="mb-3 flex items-center gap-2">
          <Search size={17} className="text-teal-700" />
          <h4 className="text-sm font-semibold">评测集</h4>
        </div>
        <div className="space-y-3">
          {["高血压患者如何随访？", "药品不良反应如何记录？", "无证据回答如何处理？"].map(
            (item, index) => (
              <div className="flex min-h-11 items-center gap-3 border-t border-zinc-100 pt-3" key={item}>
                <span className="grid h-7 w-7 place-items-center rounded-md bg-zinc-100 text-xs font-semibold">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm">{item}</span>
                <span className="text-xs text-zinc-500">通过</span>
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  const className =
    status === "indexed"
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : status === "processing"
        ? "bg-indigo-50 text-indigo-700 border-indigo-200"
        : status === "failed"
          ? "bg-rose-50 text-rose-700 border-rose-200"
          : "bg-amber-50 text-amber-700 border-amber-200";
  return (
    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${className}`}>
      {statusText[status]}
    </span>
  );
}

function ApprovalBadge({ status }: { status: ApprovalStatus }) {
  const className =
    status === "approved"
      ? "bg-emerald-50 text-emerald-700"
      : status === "rejected"
        ? "bg-rose-50 text-rose-700"
        : "bg-amber-50 text-amber-700";
  return (
    <span className={`rounded-md px-2 py-1 text-xs font-medium ${className}`}>
      {approvalText[status]}
    </span>
  );
}

function TodoIcon({ status }: { status: TodoStatus }) {
  if (status === "completed") {
    return <CheckCircle2 size={18} className="text-emerald-700" />;
  }
  if (status === "blocked") {
    return <XCircle size={18} className="text-rose-700" />;
  }
  if (status === "in_progress") {
    return <Activity size={18} className="text-indigo-700" />;
  }
  return <Archive size={18} className="text-zinc-500" />;
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate font-medium text-zinc-800">{value}</span>
    </div>
  );
}

function headerTitle(view: View, sessionTitle: string) {
  if (view === "chat") {
    return sessionTitle;
  }
  if (view === "documents") {
    return "知识库文档";
  }
  if (view === "tasks") {
    return "任务与 Agent";
  }
  if (view === "approvals") {
    return "审批中心";
  }
  return "评估面板";
}
