import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { api } from "../api/client";
import type { ImportBatch } from "../api/types";
import ImportPage from "./ImportPage";

const batch: ImportBatch = {
  id: "batch-1",
  sourceAccountId: "account-1",
  filename: "statement.csv",
  status: "NEEDS_REVIEW",
  totalRows: 2,
  validRows: 2,
  needsReviewRows: 1,
  duplicateRows: 0,
  ignoredRows: 0,
  errors: [],
  createdAt: "2026-08-09",
  updatedAt: "2026-08-09",
};

function renderPage() {
  return render(<MemoryRouter><ImportPage /></MemoryRouter>);
}

describe("ImportPage", () => {
  it("selects one source and uploads one file", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([{ id: "account-1", provider: "DBS", displayName: "DBS Current", defaultCurrency: "SGD", active: true }]);
    vi.spyOn(api.imports, "list").mockResolvedValue([]);
    const upload = vi.spyOn(api.imports, "upload").mockResolvedValue(batch);
    renderPage();

    await user.selectOptions(await screen.findByLabelText("Source account"), "account-1");
    const file = new File(["date,amount"], "statement.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    expect(screen.getByText("statement.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    expect(upload).toHaveBeenCalledWith("account-1", file);
    expect(await screen.findByText(/Parsed 2 rows/)).toBeInTheDocument();
  });

  it("renders an API problem with retry guidance", async () => {
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([]);
    vi.spyOn(api.imports, "list").mockRejectedValue(new Error("Draft index is temporarily unavailable."));
    renderPage();
    expect(await screen.findByText("Draft index is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });

  it("offers only supported sources and derives accepted formats", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([
      { id: "manual", provider: "MANUAL", displayName: "Manual", defaultCurrency: "SGD", active: true },
      { id: "revolut", provider: "REVOLUT", displayName: "Revolut", defaultCurrency: "EUR", active: true },
      { id: "dbs", provider: "DBS", displayName: "DBS", defaultCurrency: "SGD", active: true },
      { id: "mastercard", provider: "MASTERCARD", displayName: "Mastercard", defaultCurrency: "EUR", active: true },
    ]);
    vi.spyOn(api.imports, "list").mockResolvedValue([]);
    renderPage();

    const source = await screen.findByLabelText("Source account");
    expect(screen.queryByRole("option", { name: /Manual/ })).not.toBeInTheDocument();
    await user.selectOptions(source, "revolut");
    expect(screen.getByLabelText("Statement file")).toHaveAttribute("accept", ".csv,text/csv");
    expect(screen.getByText("Upload the original Revolut CSV export.")).toBeInTheDocument();
    await user.selectOptions(source, "dbs");
    expect(screen.getByLabelText("Statement file").getAttribute("accept")).toContain(".xlsx");
    await user.selectOptions(source, "mastercard");
    expect(screen.getByLabelText("Statement file").getAttribute("accept")).toContain(".xlsx");
    expect(screen.getByText("Upload the original Mastercard XLS, XLSX, or CSV export.")).toBeInTheDocument();
    expect(screen.getByText("Choose statement")).toBeInTheDocument();
  });
});
