import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import App from "./App";

describe("app navigation", () => {
  it("moves between lazy nested routes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url === "/health"
        ? { status: "ok" }
        : url.includes("/transactions")
          ? { items: [], page: 1, page_size: 25, total: 0 }
          : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "The shape of your ledger" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("link", { name: "Transactions" })[0]!);
    expect(await screen.findByRole("heading", { name: "Transactions" })).toBeInTheDocument();
  });
});
