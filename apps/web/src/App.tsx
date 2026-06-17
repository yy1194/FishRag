import { Bot, Database, FileUp, Send, ShieldCheck } from "lucide-react";

const conversations = ["医学指南问答", "知识库入库检查", "RAG 评估任务"];
const sources = [
  { title: "高血压基层诊疗指南", meta: "PDF · 第 12 页 · chunk-0042" },
  { title: "药品不良反应处理 SOP", meta: "DOCX · 第 3 节 · chunk-0017" },
  { title: "内部培训 FAQ", meta: "MD · 问答条目 · chunk-0008" },
];

export function App() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_340px]">
        <aside className="hidden border-r border-slate-200 bg-white px-4 py-5 lg:block">
          <div className="mb-6 flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-cyan-700 text-white">
              <Bot size={22} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">FishRag</h1>
              <p className="text-sm text-slate-500">医学知识库 Agent</p>
            </div>
          </div>
          <button className="mb-5 flex h-10 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-medium text-white">
            <FileUp size={17} />
            上传文档
          </button>
          <nav className="space-y-2">
            {conversations.map((item) => (
              <button
                className="w-full rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                key={item}
              >
                {item}
              </button>
            ))}
          </nav>
        </aside>

        <section className="flex min-w-0 flex-col">
          <header className="flex min-h-16 flex-col justify-center gap-3 border-b border-slate-200 bg-white px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              <h2 className="text-base font-semibold">医学资料问答</h2>
              <p className="text-sm text-slate-500">基于知识库证据回答，保留引用来源</p>
            </div>
            <div className="flex w-full items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 sm:w-auto">
              <ShieldCheck size={16} />
              审批规则已启用
            </div>
          </header>

          <div className="flex-1 space-y-5 overflow-auto px-4 py-5 sm:px-8 sm:py-6">
            <article className="max-w-3xl rounded-lg border border-slate-200 bg-white p-5">
              <p className="text-sm leading-6 text-slate-700">
                请查询高血压患者用药注意事项，并标注知识库来源。
              </p>
            </article>
            <article className="max-w-3xl rounded-lg border border-cyan-100 bg-cyan-50 p-5">
              <p className="text-sm leading-6 text-slate-800">
                已检索到 3 条相关证据。后续将由 RAG 召回、重排和医学安全审核模块生成带引用回答。
              </p>
            </article>
          </div>

          <footer className="border-t border-slate-200 bg-white p-5">
            <div className="flex items-end gap-3 rounded-lg border border-slate-300 bg-white p-3">
              <textarea
                className="min-h-12 flex-1 resize-none border-0 text-sm outline-none"
                placeholder="输入医学知识库问题..."
              />
              <button
                aria-label="发送"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-cyan-700 text-white"
              >
                <Send size={18} />
              </button>
            </div>
          </footer>
        </section>

        <aside className="hidden border-l border-slate-200 bg-white px-5 py-5 xl:block">
          <div className="mb-5 flex items-center gap-2">
            <Database size={18} />
            <h2 className="text-base font-semibold">证据片段</h2>
          </div>
          <div className="space-y-3">
            {sources.map((source) => (
              <div className="rounded-lg border border-slate-200 p-4" key={source.title}>
                <h3 className="text-sm font-medium">{source.title}</h3>
                <p className="mt-2 text-xs text-slate-500">{source.meta}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
