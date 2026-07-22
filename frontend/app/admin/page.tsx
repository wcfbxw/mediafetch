import Link from "next/link";
import { BilibiliLoginPanel } from "@/components/BilibiliLoginPanel";
import { PlatformCookiePanel } from "@/components/PlatformCookiePanel";

export default function AdminPage() {
  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-2xl">
        <header className="mb-8 flex items-center justify-between">
          <Link href="/" className="text-xl font-black tracking-tight">
            <span className="text-cobalt-600 dark:text-blue-400">Media</span>Fetch
          </Link>
          <Link href="/" className="min-h-11 rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold dark:border-slate-700">
            返回首页
          </Link>
        </header>
        <div className="space-y-6">
          <BilibiliLoginPanel />
          <PlatformCookiePanel />
        </div>
      </div>
    </main>
  );
}
