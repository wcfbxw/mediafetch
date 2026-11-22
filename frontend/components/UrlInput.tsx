"use client";

import { FormEvent, useMemo, useState } from "react";
import { extractHttpUrl } from "@/lib/url";

type Props = {
  busy?: boolean;
  onSubmit: (url: string) => void | Promise<void>;
};

function detectPlatformLabel(text: string): string | null {
  const candidate = (extractHttpUrl(text) || text).toLowerCase();
  if (!candidate) return null;
  const rules: Array<[string[], string]> = [
    [["douyin.com", "iesdouyin.com"], "抖音 · 无水印原流"],
    [["tiktok.com"], "TikTok · 无水印原流"],
    [["xiaohongshu.com", "xhslink.com"], "小红书 · 原片/实况图集"],
    [["kuaishou.com", "chenzhongtech.com", "gifshow.com"], "快手 · 无水印原片/图集"],
    [["bilibili.com", "b23.tv"], "哔哩哔哩 · 高码率 DASH"],
    [["youtube.com", "youtu.be"], "YouTube · 4K/音频"],
    [["x.com", "twitter.com", "t.co"], "X (Twitter) · 原画媒体"],
    [["instagram.com"], "Instagram · Reels/图集"],
    [["weibo.com", "weibo.cn"], "微博 · 原画视频"],
    [["pipixia.com"], "皮皮虾 · 无水印原片"],
    [["ixigua.com"], "西瓜视频"],
    [["reddit.com", "redd.it"], "Reddit"],
    [["vimeo.com"], "Vimeo"],
  ];
  for (const [domains, label] of rules) {
    if (domains.some((domain) => candidate.includes(domain))) {
      return label;
    }
  }
  if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
    return "通用平台引擎 · 自动识别";
  }
  return null;
}

export function UrlInput({ busy = false, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [inputMessage, setInputMessage] = useState("");
  const [isError, setIsError] = useState(false);

  const detectedPlatform = useMemo(() => detectPlatformLabel(value), [value]);

  function applySharedText(text: string): string | null {
    const extracted = extractHttpUrl(text);
    if (!extracted) {
      setValue(text.trim());
      setIsError(true);
      setInputMessage("没有找到 http 或 https 视频链接，请检查粘贴内容");
      return null;
    }
    setValue(extracted);
    setIsError(false);
    setInputMessage(text.trim() === extracted ? "" : "已从分享文案中自动提取链接");
    return extracted;
  }

  async function paste() {
    setInputMessage("");
    try {
      applySharedText(await navigator.clipboard.readText());
    } catch {
      setIsError(true);
      setInputMessage("无法读取剪贴板，请长按输入框后粘贴");
    }
  }

  function clear() {
    setValue("");
    setInputMessage("");
    setIsError(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const extracted = applySharedText(value);
    if (extracted) void onSubmit(extracted);
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="视频链接解析" aria-busy={busy}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label
          htmlFor="video-url"
          className="block text-sm font-bold text-slate-800 dark:text-slate-100"
        >
          视频链接或分享文案
        </label>
        {detectedPlatform ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-cobalt-50 px-2.5 py-1 text-xs font-bold text-cobalt-700 dark:bg-indigo-950/70 dark:text-indigo-300">
            <span className="h-1.5 w-1.5 rounded-full bg-mint" />
            {detectedPlatform}
          </span>
        ) : (
          <span className="hidden text-xs text-slate-400 sm:block">
            支持直接粘贴抖音、小红书、快手、B站、TikTok、YouTube、X 等整段分享口令
          </span>
        )}
      </div>

      <div className="rounded-[22px] border border-slate-200 bg-slate-50/90 p-2 shadow-inner shadow-slate-200/40 focus-within:border-cobalt-500 focus-within:bg-white focus-within:ring-4 focus-within:ring-cobalt-500/10 sm:flex sm:items-center sm:gap-2 dark:border-slate-700 dark:bg-slate-950/70 dark:shadow-none dark:focus-within:bg-slate-950">
        <div className="relative flex min-w-0 flex-1 items-center">
          <span
            aria-hidden="true"
            className="pointer-events-none ml-3.5 h-2.5 w-2.5 shrink-0 rounded-full bg-mint shadow-[0_0_0_5px_rgba(24,185,129,.12)]"
          />
          <input
            id="video-url"
            type="text"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            disabled={busy}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setInputMessage("");
              setIsError(false);
            }}
            placeholder="粘贴视频/图集链接或带文案的分享口令…"
            aria-describedby={inputMessage ? "url-input-message" : undefined}
            className="min-h-14 w-full min-w-0 flex-1 border-0 bg-transparent px-3 py-3 text-base font-medium text-slate-950 outline-none placeholder:font-normal placeholder:text-slate-400 focus:ring-0 disabled:opacity-60 dark:text-white"
          />
          <div className="flex shrink-0 items-center gap-1 pr-1">
            {value ? (
              <button
                type="button"
                onClick={clear}
                disabled={busy}
                className="min-h-10 rounded-xl px-2.5 text-xs font-bold text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 disabled:opacity-50 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                清空
              </button>
            ) : null}
            <button
              type="button"
              onClick={paste}
              disabled={busy}
              className="min-h-10 rounded-xl px-3 text-sm font-bold text-cobalt-600 hover:bg-cobalt-50 disabled:opacity-50 dark:text-indigo-300 dark:hover:bg-slate-800"
            >
              粘贴
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={busy || !value.trim()}
          aria-label={busy ? "正在解析" : "解析视频"}
          className="mt-2 min-h-14 w-full shrink-0 rounded-2xl bg-slate-950 px-7 font-black text-white shadow-lg shadow-slate-950/15 hover:bg-cobalt-600 disabled:cursor-not-allowed disabled:opacity-50 sm:mt-0 sm:w-auto dark:bg-signal dark:text-slate-950 dark:hover:bg-lime-300"
        >
          {busy ? "正在解析…" : "解析无水印 →"}
        </button>
      </div>

      {inputMessage ? (
        <p
          id="url-input-message"
          className={`text-sm ${
            isError
              ? "text-amber-700 dark:text-amber-300"
              : "text-emerald-700 dark:text-emerald-300"
          }`}
          role={isError ? "alert" : "status"}
        >
          {inputMessage}
        </p>
      ) : null}
    </form>
  );
}
