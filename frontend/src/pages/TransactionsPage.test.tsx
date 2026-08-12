import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { Transaction } from "../api/types";
import TransactionsPage from "./TransactionsPage";

const transaction: Transaction = {
  id: "transaction-1",
  revision: 4,
  date: "2026-08-10",
  description: "Synthetic cafe",
  amountMinor: -1250,
  currency: "EUR",
  kind: "EXPENSE",
  sourceAccountId: "account-1",
  sourceAccountName: "Manual EUR",
  categoryId: null,
  categoryName: null,
  subcategoryId: null,
  subcategoryName: null,
  excluded: false,
  importBatchId: "batch-1",
};

describe("TransactionsPage", () => {
  it("confirms and permanently deletes the current revision", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([]);
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);
    vi.spyOn(api.transactions, "currencies").mockResolvedValue(["EUR"]);
    vi.spyOn(api.transactions, "list").mockResolvedValue({
      items: [transaction],
      page: 1,
      pageSize: 25,
      total: 1,
    });
    const deleteTransaction = vi.spyOn(api.transactions, "delete").mockResolvedValue();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<TransactionsPage />);
    await user.click(await screen.findByRole("button", { name: "Edit Synthetic cafe" }));
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("This cannot be undone"));
    await waitFor(() => expect(deleteTransaction).toHaveBeenCalledWith("transaction-1", 4));
  });

  it("stores an exactly parsed signed amount correction", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([]);
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);
    vi.spyOn(api.transactions, "currencies").mockResolvedValue(["EUR"]);
    vi.spyOn(api.transactions, "list").mockResolvedValue({
      items: [transaction],
      page: 1,
      pageSize: 25,
      total: 1,
    });
    const patch = vi.spyOn(api.transactions, "patch").mockResolvedValue({
      ...transaction,
      amountMinor: -1999,
      revision: 5,
    });

    render(<TransactionsPage />);
    expect(await screen.findByLabelText("Search description")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Synthetic cafe" }));
    const amount = screen.getByLabelText("Amount (EUR)");
    await user.clear(amount);
    await user.type(amount, "-19.99");
    await user.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      "transaction-1",
      expect.objectContaining({ expectedRevision: 4, amountMinor: -1999 }),
    ));
  });
});
