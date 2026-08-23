import { formatBytes, formatEta } from "@/lib/format";
import type { Job } from "@/lib/types";

const STATUS_LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  inspecting: "正在解析",
  downloading: "正在下载",
  downloading_video: "正在下载视频轨",
  downloading_audio: "正在下载音频轨",
  merging: "正在无损合并",
  processing: "正在转换格式",
  ready: "下载已准备好",
  failed: "任务失败",
  cancelled: "任务已取消",
  expired: "文件已过期",
};

const STAGES = ["排队", "下载", "处理", "完成"];

function stageIndex(status: Job["status"]): number {
  if (["queued", "inspecting"].includes(status)) return 0;
  if (["downloading", "downloading_video", "downloading_audio"].includes(status)) return 1;
  if (["merging", "processing"].includes(status)) return 2;
  if (status === "ready") return 3;
  return -1;
}

type Props = {
  job: Job;
  onCancel?: () => void;
};

export function JobProgress({ job, onCancel }: Props) {
  const active = !["ready", "failed", "cancelled", "expired"].includes(job.status);
  const currentStage = stageIndex(job.status);
  const failed = job.status === "failed";
  return (
    <section
      aria-labelledby="progress-heading"
      className={`overflow-hidden rounded-[28px] border bg-white shadow-panel dark:bg-slate-900 ${
        failed ? "border-red-200 dark:border-red-900" : "border-slate-200/80 dark:border-slate-800"
      }`}
    >
      <div className="border-b border-slate-100 bg-slate-950 p-5 text-white sm:p-7 dark:border-slate-800">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.2em] text-signal">Live task</p>
            <h2 id="progress-heading" className="mt-2 text-2xl font-black tracking-tight">
              {STATUS_LABELS[job.status]}
            </h2>
            <p className="mt-1 text-sm text-slate-300">{job.message}</p>
          </div>
          <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-bold tabular-nums">
            {Math.round(job.progress)}%
          </span>
        </div>

        <ol className="mt-7 grid grid-cols-4 gap-2" aria-label="任务阶段">
          {STAGES.map((stage, index) => {
            const passed = currentStage >= index;
            return (
              <li key={stage} className="min-w-0">
                <span className={`mb-2 block h-1.5 rounded-full ${passed ? "bg-signal" : "bg-white/15"}`} />
                <span className={`block truncate text-[11px] font-bold ${passed ? "text-white" : "text-slate-500"}`}>
                  {stage}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="p-5 sm:p-7">
      <div>
        <div className="mb-2 flex justify-between text-sm font-semibold">
          <span>总进度</span>
          <span className="tabular-nums">{Math.round(job.progress)}%</span>
        </div>
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(job.progress)}
          className="h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-cobalt-500 via-indigo-400 to-mint transition-[width] duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-slate-200 bg-slate-200 sm:grid-cols-4 dark:border-slate-700 dark:bg-slate-700">
        <div className="bg-slate-50 p-4 dark:bg-slate-800/80">
          <dt className="text-[11px] font-bold uppercase tracking-wide text-slate-400">下载速度</dt>
          <dd className="mt-1.5 font-black tabular-nums">{job.speed ? `${formatBytes(job.speed)}/s` : "—"}</dd>
        </div>
        <div className="bg-slate-50 p-4 dark:bg-slate-800/80">
          <dt className="text-[11px] font-bold uppercase tracking-wide text-slate-400">已下载</dt>
          <dd className="mt-1.5 font-black tabular-nums">{formatBytes(job.downloaded_bytes)}</dd>
        </div>
        <div className="bg-slate-50 p-4 dark:bg-slate-800/80">
          <dt className="text-[11px] font-bold uppercase tracking-wide text-slate-400">总大小</dt>
          <dd className="mt-1.5 font-black tabular-nums">{formatBytes(job.total_bytes)}</dd>
        </div>
        <div className="bg-slate-50 p-4 dark:bg-slate-800/80">
          <dt className="text-[11px] font-bold uppercase tracking-wide text-slate-400">剩余时间</dt>
          <dd className="mt-1.5 font-black tabular-nums">{active ? formatEta(job.eta) : "—"}</dd>
        </div>
      </dl>

      {active ? (
        <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-cobalt-100 bg-cobalt-50/70 p-4 sm:flex-row sm:items-center sm:justify-between dark:border-indigo-900/60 dark:bg-indigo-950/30">
          <p className="text-xs leading-5 text-slate-600 dark:text-slate-300">
            任务在服务器后台持续处理，刷新或关闭页面不会中断；再次打开会自动恢复进度。
          </p>
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="min-h-11 shrink-0 rounded-xl border border-slate-300 bg-white px-4 text-sm font-bold hover:border-red-300 hover:text-red-600 dark:border-slate-600 dark:bg-slate-900 dark:hover:border-red-800"
            >
              取消任务
            </button>
          ) : null}
        </div>
      ) : null}

      {job.error ? (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
          {job.error.message}
        </div>
      ) : null}

      {job.status === "ready" && job.download_url ? (
        <a
          href={job.download_url}
          aria-label="下载最终文件"
          className="mt-6 flex min-h-14 w-full items-center justify-center rounded-2xl bg-emerald-600 px-6 text-base font-black text-white shadow-lg shadow-emerald-600/20 hover:bg-emerald-700"
        >
          下载最终文件 ↓
        </a>
      ) : null}
      </div>
    </section>
  );
}
