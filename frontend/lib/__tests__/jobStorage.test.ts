import { beforeEach, expect, test } from "vitest";
import {
  LAST_JOB_STORAGE_KEY,
  readStoredJobId,
  rememberJob,
  validJobId,
} from "@/lib/jobStorage";
import type { Job } from "@/lib/types";

const job: Job = {
  job_id: "valid_job_id_1234567890",
  status: "processing",
  progress: 92,
  speed: null,
  downloaded_bytes: 100,
  total_bytes: 100,
  eta: null,
  message: "processing",
  download_url: null,
  error: null,
};

beforeEach(() => window.localStorage.clear());

test("stores an active job and keeps a completed download restorable", () => {
  rememberJob(job);
  expect(readStoredJobId()).toBe(job.job_id);

  rememberJob({ ...job, status: "ready", download_url: "/api/v1/files/token" });
  expect(readStoredJobId()).toBe(job.job_id);
});

test("clears failed and cancelled jobs", () => {
  rememberJob(job);
  rememberJob({ ...job, status: "cancelled" });
  expect(readStoredJobId()).toBeNull();
});

test("rejects a malformed stored job id", () => {
  window.localStorage.setItem(LAST_JOB_STORAGE_KEY, "../../server/path");
  expect(readStoredJobId()).toBeNull();
  expect(window.localStorage.getItem(LAST_JOB_STORAGE_KEY)).toBeNull();
});

test("validates a job id supplied by a recovery link", () => {
  expect(validJobId(job.job_id)).toBe(job.job_id);
  expect(validJobId("../../server/path")).toBeNull();
});
