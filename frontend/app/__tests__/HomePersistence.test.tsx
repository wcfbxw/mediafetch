import { render, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import Home from "@/app/page";
import { LAST_JOB_STORAGE_KEY } from "@/lib/jobStorage";
import type { Job } from "@/lib/types";

const { getJobMock } = vi.hoisted(() => ({ getJobMock: vi.fn() }));

vi.mock("@/lib/api", () => ({
  API_BASE: "/api/v1",
  cancelJob: vi.fn(),
  createDownload: vi.fn(),
  getJob: getJobMock,
  inspectUrl: vi.fn(),
}));

class FakeEventSource {
  onerror: ((event: Event) => void) | null = null;
  addEventListener = vi.fn();
  close = vi.fn();

  constructor(public readonly url: string) {}
}

const readyJob: Job = {
  job_id: "restored_job_id_123456789",
  status: "ready",
  progress: 100,
  speed: null,
  downloaded_bytes: 1024,
  total_bytes: 1024,
  eta: 0,
  message: "ready",
  download_url: "/api/v1/files/restored-token",
  error: null,
};

beforeEach(() => {
  window.localStorage.clear();
  getJobMock.mockReset();
  vi.stubGlobal("EventSource", FakeEventSource);
});

test("restores the last server job after a page reload", async () => {
  window.localStorage.setItem(LAST_JOB_STORAGE_KEY, readyJob.job_id);
  getJobMock.mockResolvedValue(readyJob);

  const { container } = render(<Home />);

  await waitFor(() => expect(getJobMock).toHaveBeenCalledWith(readyJob.job_id));
  await waitFor(() =>
    expect(
      container.querySelector('a[href="/api/v1/files/restored-token"]'),
    ).toBeInTheDocument(),
  );
  expect(window.localStorage.getItem(LAST_JOB_STORAGE_KEY)).toBe(readyJob.job_id);
});

test("restores a task from a one-time URL fragment", async () => {
  window.history.replaceState(null, "", `/#job=${readyJob.job_id}`);
  getJobMock.mockResolvedValue(readyJob);

  render(<Home />);

  await waitFor(() => expect(getJobMock).toHaveBeenCalledWith(readyJob.job_id));
  expect(window.localStorage.getItem(LAST_JOB_STORAGE_KEY)).toBe(readyJob.job_id);
  expect(window.location.hash).toBe("");
});
