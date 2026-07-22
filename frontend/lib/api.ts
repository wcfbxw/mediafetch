import type {
  ApiError,
  BilibiliLoginPoll,
  BilibiliLoginStart,
  Inspection,
  Job,
  OperatorPlatform,
  PlatformSessionStatus,
} from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const body = (await response.json().catch(() => null)) as T | ApiError | null;
  if (!response.ok) {
    const message =
      body && typeof body === "object" && "error" in body
        ? body.error.message
        : "请求失败，请稍后重试";
    throw new Error(message);
  }
  return body as T;
}

export function inspectUrl(url: string): Promise<Inspection> {
  return request<Inspection>("/inspect", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function createDownload(payload: {
  inspect_id: string;
  video_format_id: string;
  audio_format_id: string | null;
  output_container: string;
  compatibility_mode: boolean;
}): Promise<{ job_id: string; status: "queued" }> {
  return request("/downloads", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function cancelJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
}

function adminHeaders(token: string): HeadersInit {
  return { "X-Admin-Token": token };
}

export function getBilibiliSession(token: string): Promise<PlatformSessionStatus> {
  return request("/admin/bilibili/status", { headers: adminHeaders(token) });
}

export function beginBilibiliLogin(token: string): Promise<BilibiliLoginStart> {
  return request("/admin/bilibili/login", {
    method: "POST",
    headers: adminHeaders(token),
  });
}

export function pollBilibiliLogin(
  token: string,
  loginId: string,
): Promise<BilibiliLoginPoll> {
  return request(`/admin/bilibili/login/${encodeURIComponent(loginId)}`, {
    headers: adminHeaders(token),
  });
}

export function clearBilibiliSession(token: string): Promise<PlatformSessionStatus> {
  return request("/admin/bilibili/session", {
    method: "DELETE",
    headers: adminHeaders(token),
  });
}

export function getPlatformSession(
  token: string,
  platform: OperatorPlatform,
): Promise<PlatformSessionStatus> {
  return request(`/admin/platforms/${platform}/status`, { headers: adminHeaders(token) });
}

export async function uploadPlatformCookies(
  token: string,
  platform: OperatorPlatform,
  file: File,
): Promise<PlatformSessionStatus> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/admin/platforms/${platform}/cookies`, {
    method: "PUT",
    headers: adminHeaders(token),
    body: form,
  });
  const body = (await response.json().catch(() => null)) as PlatformSessionStatus | ApiError | null;
  if (!response.ok) {
    const message = body && typeof body === "object" && "error" in body
      ? body.error.message
      : "Cookie 文件上传失败";
    throw new Error(message);
  }
  return body as PlatformSessionStatus;
}

export function clearPlatformSession(
  token: string,
  platform: OperatorPlatform,
): Promise<PlatformSessionStatus> {
  return request(`/admin/platforms/${platform}/session`, {
    method: "DELETE",
    headers: adminHeaders(token),
  });
}
