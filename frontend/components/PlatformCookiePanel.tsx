"use client";

import { useEffect, useState } from "react";
import {
  clearPlatformSession,
  getPlatformSession,
  uploadPlatformCookies,
} from "@/lib/api";
import type {
  OperatorPlatform,
  PlatformSessionStatus,
} from "@/lib/types";

const TOKEN_STORAGE_KEY = "mediafetch-admin-token";
const PLATFORMS: Array<{ id: OperatorPlatform; name: string; hint: string }> = [
  { id: "douyin", name: "抖音", hint: "新鲜的 douyin.com 会话" },
  { id: "instagram", name: "Instagram", hint: "instagram.com 登录会话" },
  { id: "youtube", name: "YouTube", hint: "youtube.com / google.com 登录会话" },
];

function dateText(value: number | null): string {
  return value ? new Date(value * 1000).toLocaleString("zh-CN") : "会话 Cookie";
}

export function PlatformCookiePanel() {
  const [token, setToken] = useState("");
  const [statuses, setStatuses] = useState<Partial<Record<OperatorPlatform, PlatformSessionStatus>>>({});
  const [busy, setBusy] = useState<OperatorPlatform | "refresh" | "">("");
  const [message, setMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const syncToken = () => setToken(window.sessionStorage.getItem(TOKEN_STORAGE_KEY) || "");
    syncToken();
    window.addEventListener("mediafetch-admin-authorized", syncToken);
    return () => window.removeEventListener("mediafetch-admin-authorized", syncToken);
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    setBusy("refresh");
    Promise.all(
      PLATFORMS.map(async ({ id }) => [id, await getPlatformSession(token, id)] as const),
    )
      .then((entries) => {
        if (active) setStatuses(Object.fromEntries(entries));
      })
      .catch((error) => {
        if (active) setErrorMessage(error instanceof Error ? error.message : "会话状态读取失败");
      })
      .finally(() => {
        if (active) setBusy("");
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function upload(platform: OperatorPlatform, file: File | undefined) {
    if (!file || !token) return;
    setBusy(platform);
    setMessage("");
    setErrorMessage("");
    try {
      const status = await uploadPlatformCookies(token, platform, file);
      setStatuses((current) => ({ ...current, [platform]: status }));
      setMessage(`${PLATFORMS.find((item) => item.id === platform)?.name} 会话已安全更新`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Cookie 文件上传失败");
    } finally {
      setBusy("");
    }
  }

  async function clear(platform: OperatorPlatform) {
    if (!token || !window.confirm("确定删除服务器上的这个平台会话吗？")) return;
    setBusy(platform);
    setMessage("");
    setErrorMessage("");
    try {
      const status = await clearPlatformSession(token, platform);
      setStatuses((current) => ({ ...current, [platform]: status }));
      setMessage("平台会话已删除");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "删除会话失败");
    } finally {
      setBusy("");
    }
  }

  if (!token) return null;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft sm:p-7 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="text-xl font-black">其他平台会话</h2>
      <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
        这些平台没有可安全接入的扫码接口。请从已登录浏览器导出当前平台的 Netscape cookies.txt；文件只允许包含对应平台域名，最大 128 KB。
      </p>

      <div className="mt-5 space-y-4">
        {PLATFORMS.map((platform) => {
          const status = statuses[platform.id];
          return (
            <article key={platform.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold">{platform.name}</h3>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${status?.configured ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
                      {status?.configured ? "已配置" : "未配置"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {status?.configured ? `更新：${dateText(status.updated_at)}` : platform.hint}
                  </p>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <label className="flex min-h-11 cursor-pointer items-center justify-center rounded-xl bg-cobalt-600 px-4 text-sm font-bold text-white">
                    {busy === platform.id ? "处理中…" : status?.configured ? "更新 Cookie" : "导入 Cookie"}
                    <input
                      type="file"
                      accept=".txt,text/plain"
                      disabled={Boolean(busy)}
                      className="sr-only"
                      onChange={(event) => {
                        void upload(platform.id, event.currentTarget.files?.[0]);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                  {status?.configured ? (
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => void clear(platform.id)}
                      className="min-h-11 rounded-xl border border-red-300 px-4 text-sm font-bold text-red-700 disabled:opacity-50 dark:border-red-900 dark:text-red-300"
                    >
                      删除
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {busy === "refresh" ? <p className="mt-4 text-sm text-slate-500">正在读取会话状态…</p> : null}
      {message ? <p aria-live="polite" className="mt-4 text-sm text-emerald-700 dark:text-emerald-300">{message}</p> : null}
      {errorMessage ? <p role="alert" className="mt-4 text-sm text-red-600">{errorMessage}</p> : null}
      <p className="mt-5 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
        Cookie 内容不会返回前端、不会写入日志，并在每次解析或下载时复制到进程私有临时文件。不要导出整个浏览器的 Cookie 数据库。
      </p>
    </section>
  );
}
