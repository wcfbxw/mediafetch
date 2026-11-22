"use client";

import { resolveBackendUrl } from "@/lib/api";
import type { GalleryItem } from "@/lib/types";

type Props = {
  items: GalleryItem[];
  zipUrl?: string | null;
};

export function GalleryGrid({ items, zipUrl }: Props) {
  if (!items.length) return null;

  return (
    <section aria-labelledby="gallery-heading" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-emerald-600 dark:text-emerald-400">
            Clean Gallery · 无水印原图集
          </p>
          <h3 id="gallery-heading" className="mt-1 text-xl font-black tracking-tight">
            共提取 {items.length} 张无水印高清原图
          </h3>
        </div>
        {zipUrl ? (
          <a
            href={resolveBackendUrl(zipUrl)}
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 text-sm font-black text-white shadow-lg shadow-slate-950/15 hover:bg-cobalt-600 dark:bg-signal dark:text-slate-950 dark:hover:bg-lime-300"
          >
            📦 一键打包下载全部 ({items.length} 张 ZIP)
          </a>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {items.map((item) => (
          <article
            key={item.index}
            className="group overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/60"
          >
            <div className="relative aspect-[3/4] overflow-hidden bg-slate-100 dark:bg-slate-900">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveBackendUrl(item.preview_url)}
                alt={`图集第 ${item.index} 张`}
                loading="lazy"
                referrerPolicy="no-referrer"
                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
              />
              <span className="absolute left-2.5 top-2.5 rounded-lg bg-black/70 px-2 py-0.5 text-[11px] font-black text-white backdrop-blur">
                #{String(item.index).padStart(2, "0")}
              </span>
              {item.live_video_url ? (
                <span className="absolute right-2.5 top-2.5 rounded-lg bg-emerald-500/90 px-2 py-0.5 text-[10px] font-black text-white">
                  LIVE 实况
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2 p-2.5">
              <a
                href={resolveBackendUrl(item.download_url)}
                className="flex min-h-9 flex-1 items-center justify-center rounded-xl bg-white px-2.5 text-xs font-black text-slate-900 shadow-sm ring-1 ring-slate-200 hover:bg-cobalt-600 hover:text-white hover:ring-cobalt-600 dark:bg-slate-800 dark:text-white dark:ring-slate-700 dark:hover:bg-cobalt-600"
              >
                下载原图 ({item.extension.toUpperCase()})
              </a>
              {item.live_video_url ? (
                <a
                  href={resolveBackendUrl(item.live_video_url)}
                  className="flex min-h-9 items-center justify-center rounded-xl bg-emerald-600 px-2.5 text-xs font-black text-white hover:bg-emerald-700"
                  title="下载无水印实况动态视频"
                >
                  实况 MP4
                </a>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
