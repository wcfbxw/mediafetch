import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { BilibiliLoginPanel } from "@/components/BilibiliLoginPanel";
import { getBilibiliSession } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getBilibiliSession: vi.fn(),
  beginBilibiliLogin: vi.fn(),
  pollBilibiliLogin: vi.fn(),
  clearBilibiliSession: vi.fn(),
}));

test("keeps the admin token out of the URL and shows session state", async () => {
  const user = userEvent.setup();
  vi.mocked(getBilibiliSession).mockResolvedValue({
    configured: false,
    updated_at: null,
    expires_at: null,
  });
  render(<BilibiliLoginPanel />);
  await user.type(screen.getByLabelText("管理员令牌"), "a".repeat(64));
  await user.click(screen.getByRole("button", { name: "验证并进入" }));
  expect(await screen.findByText("服务器平台会话")).toBeInTheDocument();
  expect(window.location.search).toBe("");
  expect(getBilibiliSession).toHaveBeenCalledWith("a".repeat(64));
});
