import { render, screen } from "@testing-library/react";
import { ErrorAlert } from "@/components/ErrorAlert";

test("shows a safe user-facing error message", () => {
  render(<ErrorAlert message="暂时不支持这个链接" />);
  expect(screen.getByRole("alert")).toHaveTextContent("暂时不支持这个链接");
});
