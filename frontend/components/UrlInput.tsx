"use client";

import { FormEvent, useState } from "react";
import { extractHttpUrl } from "@/lib/url";

type Props = {
  busy?: boolean;
  onSubmit: (url: string) => void | Promise<void>;
};

export function UrlInput({ busy = false, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [inputMessage, setInputMessage] = useState("");
  const [isError, setIsError] = useState(false);

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

  function submit(event: FormEvent) {
    event.preventDefault();
    const extracted = applySharedText(value);
    if (extracted) void onSubmit(extracted);
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="视频链接解析" aria-busy={busy}>
      <div className="flex items-end justify-between gap-4">
        <label
          htmlFor="video-url"
          className="block text-sm font-bold text-slate-800 dark:text-slate-100"
        >
          视频链接或分享文案
        </label>
        <span className="hidden text-xs text-slate-400 sm:block">支持直接粘贴整段平台分享文案</span>
      </div>
      <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-2 shadow-inner shadow-slate-200/50 focus-within:border-cobalt-500 focus-within:bg-white focus-within:ring-4 focus-within:ring-cobalt-500/10 sm:flex sm:items-center sm:gap-2 dark:border-slate-700 dark:bg-slate-950/60 dark:shadow-none dark:focus-within:bg-slate-950">
        <div className="relative min-w-0 flex-1">
          <span aria-hidden="true" className="absolute left-4 top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-mint shadow-[0_0_0_5px_rgba(24,185,129,.12)]" />
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
            placeholder="粘贴链接或整段分享文案"
            aria-describedby={inputMessage ? "url-input-message" : undefined}
            className="min-h-14 w-full rounded-2xl border-0 bg-transparent py-3 pl-10 pr-20 text-base font-medium text-slate-950 outline-none placeholder:font-normal placeholder:text-slate-400 focus:ring-0 disabled:opacity-60 dark:text-white"
          />
          <button
            type="button"
            onClick={paste}
            disabled={busy}
            className="absolute right-1.5 top-1/2 min-h-10 -translate-y-1/2 rounded-xl px-3 text-sm font-bold text-cobalt-600 hover:bg-cobalt-50 disabled:opacity-50 dark:text-indigo-300 dark:hover:bg-slate-800"
          >
            粘贴
          </button>
        </div>
        <button
          type="submit"
          disabled={busy || !value.trim()}
          aria-label={busy ? "正在解析" : "解析视频"}
          className="mt-2 min-h-14 w-full shrink-0 rounded-2xl bg-slate-950 px-7 font-bold text-white shadow-lg shadow-slate-950/15 hover:bg-cobalt-600 disabled:cursor-not-allowed disabled:opacity-50 sm:mt-0 sm:w-auto dark:bg-signal dark:text-slate-950 dark:hover:bg-lime-300"
        >
          {busy ? "正在解析…" : "解析视频 →"}
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
