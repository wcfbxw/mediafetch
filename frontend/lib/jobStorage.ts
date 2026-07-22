import type { Job, JobStatus } from "@/lib/types";

export const LAST_JOB_STORAGE_KEY = "mediafetch.last-job.v1";

const JOB_ID_PATTERN = /^[A-Za-z0-9_-]{20,128}$/;
const TERMINAL_STATUSES = new Set<JobStatus>([
  "ready",
  "failed",
  "cancelled",
  "expired",
]);

export function isTerminalJob(status: JobStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function validJobId(value: string | null): string | null {
  return value && JOB_ID_PATTERN.test(value) ? value : null;
}

export function readStoredJobId(): string | null {
  try {
    const value = window.localStorage.getItem(LAST_JOB_STORAGE_KEY);
    if (!value) return null;
    if (!validJobId(value)) {
      window.localStorage.removeItem(LAST_JOB_STORAGE_KEY);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function rememberJob(job: Job): void {
  try {
    if (!isTerminalJob(job.status) || job.status === "ready") {
      window.localStorage.setItem(LAST_JOB_STORAGE_KEY, job.job_id);
    } else if (window.localStorage.getItem(LAST_JOB_STORAGE_KEY) === job.job_id) {
      window.localStorage.removeItem(LAST_JOB_STORAGE_KEY);
    }
  } catch {
    // Safari privacy settings may disable persistent browser storage. The
    // active page still keeps receiving SSE updates in that case.
  }
}

export function forgetStoredJob(jobId?: string): void {
  try {
    if (!jobId || window.localStorage.getItem(LAST_JOB_STORAGE_KEY) === jobId) {
      window.localStorage.removeItem(LAST_JOB_STORAGE_KEY);
    }
  } catch {
    // Nothing else is required when storage is unavailable.
  }
}
