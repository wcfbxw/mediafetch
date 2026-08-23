import Link from "next/link";
import { BilibiliLoginPanel } from "@/components/BilibiliLoginPanel";
import { PlatformCookiePanel } from "@/components/PlatformCookiePanel";

export default function AdminPage() {
  return (
    <main className="min-h-screen px-4 py-5 sm:px-6 sm:py-8">
      <div className="mx-auto max-w-3xl">
        <header className="flex items-center justify-between">
          <Link href="/" className="group flex items-center gap-2.5" aria-label="MediaFetch 首页">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-[11px] font-black tracking-tighter text-signal group-hover:bg-cobalt-600 dark:bg-signal dark:text-slate-950">MF</span>
            <span className="text-lg font-black tracking-[-0.04em]">MediaFetch</span>
          </Link>
          <Link href="/" className="grid min-h-11 place-items-center rounded-xl border border-slate-200 bg-white/70 px-4 text-sm font-bold hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900/70">
            ← 返回首页
          </Link>
        </header>
        <section className="pb-8 pt-12 sm:pt-16">
          <p className="text-xs font-black uppercase tracking-[0.2em] text-cobalt-600 dark:text-indigo-300">Operator console</p>
          <h1 className="mt-3 text-3xl font-black tracking-[-0.04em] sm:text-4xl">平台会话管理</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500 dark:text-slate-400">统一管理服务器用于解析的受控平台会话。凭据只保存在隔离卷中，不会返回到前端或写入日志。</p>
        </section>
        <div className="space-y-6">
          <BilibiliLoginPanel />
          <PlatformCookiePanel />
        </div>
      </div>
    </main>
  );
}
