import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import AccountsPage from "./AccountsPage";

describe("AccountsPage", () => {
  it("creates, renames, and deactivates generic accounts", async () => {
    const user = userEvent.setup();
    const accounts = [
      { id: "unknown", name: "Unknown", defaultCurrency: "EUR", active: true },
      { id: "daily", name: "Daily", defaultCurrency: "EUR", active: true },
    ];
    vi.spyOn(api.accounts, "list")
      .mockResolvedValueOnce(accounts)
      .mockResolvedValue([...accounts, { id: "cash", name: "Cash", defaultCurrency: "USD", active: true }]);
    const create = vi.spyOn(api.accounts, "create").mockResolvedValue({ id: "cash", name: "Cash", defaultCurrency: "USD", active: true });
    const patch = vi.spyOn(api.accounts, "patch").mockImplementation(async (id, input) => ({ ...accounts.find((account) => account.id === id)!, name: input.name ?? accounts.find((account) => account.id === id)!.name, active: input.active ?? true }));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<AccountsPage />);
    expect(await screen.findByText("Unknown")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.type(screen.getByLabelText("Account name"), "Cash");
    await user.clear(screen.getByLabelText("Default currency"));
    await user.type(screen.getByLabelText("Default currency"), "usd");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(create).toHaveBeenCalledWith({ name: "Cash", defaultCurrency: "USD" });

    await user.click((await screen.findAllByRole("button", { name: "Rename" }))[0]!);
    const rename = screen.getByLabelText("Rename Unknown");
    await user.clear(rename);
    await user.type(rename, "Unassigned");
    await user.click(screen.getByRole("button", { name: "Save name" }));
    expect(patch).toHaveBeenCalledWith("unknown", { name: "Unassigned" });

    await user.click((await screen.findAllByRole("button", { name: "Deactivate" }))[0]!);
    await waitFor(() => expect(patch).toHaveBeenCalledWith("unknown", { active: false }));
  });

  it("rejects non-ISO account currency codes", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.accounts, "list").mockResolvedValue([]);
    const create = vi.spyOn(api.accounts, "create");
    render(<AccountsPage />);
    await user.click(await screen.findByRole("button", { name: "Create account" }));
    await user.type(screen.getByLabelText("Account name"), "Invalid currency account");
    await user.clear(screen.getByLabelText("Default currency"));
    await user.type(screen.getByLabelText("Default currency"), "zzz");
    expect(screen.getByText("Enter a valid ISO 4217 currency code.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    expect(create).not.toHaveBeenCalled();
  });
});
