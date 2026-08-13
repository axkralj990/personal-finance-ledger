import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { api } from "../api/client";
import type { ImportBatch } from "../api/types";
import ImportPage from "./ImportPage";

const batch: ImportBatch = {
  id: "batch-1",
  accountId: "account-1",
  filename: "statement.csv",
  status: "NEEDS_REVIEW",
  totalRows: 2,
  validRows: 2,
  needsReviewRows: 1,
  duplicateRows: 0,
  includedRows: 2,
  ignoredRows: 0,
  auditRows: 0,
  blockedRows: 0,
  errors: [],
  revision: 1,
  mappingRevision: 0,
  currentMappingOrigin: null,
  currentMapping: null,
  currentTemplateId: null,
  currentTemplateVersionId: null,
  mappingDiagnostics: [],
  createdAt: "2026-08-09",
  updatedAt: "2026-08-09",
};

function renderPage() {
  return render(<MemoryRouter><ImportPage /></MemoryRouter>);
}

describe("ImportPage", () => {
  it("selects one source and uploads one file", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.accounts, "list").mockResolvedValue([{ id: "account-1", name: "Everyday account", defaultCurrency: "EUR", active: true }]);
    vi.spyOn(api.imports, "list").mockResolvedValue([]);
    const upload = vi.spyOn(api.imports, "upload").mockResolvedValue(batch);
    renderPage();

    await user.selectOptions(await screen.findByLabelText("Destination account"), "account-1");
    const file = new File(["date,amount"], "statement.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    expect(screen.getByText("statement.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload and inspect" }));

    expect(upload).toHaveBeenCalledWith("account-1", file);
  });

  it("renders an API problem with retry guidance", async () => {
    vi.spyOn(api.accounts, "list").mockResolvedValue([]);
    vi.spyOn(api.imports, "list").mockRejectedValue(new Error("Draft index is temporarily unavailable."));
    renderPage();
    expect(await screen.findByText("Draft index is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });

  it("offers every active destination the same universal file formats", async () => {
    vi.spyOn(api.accounts, "list").mockResolvedValue([
      { id: "manual", name: "Manual", defaultCurrency: "EUR", active: true },
      { id: "cash", name: "Household cash", defaultCurrency: "EUR", active: true },
      { id: "bank", name: "Everyday account", defaultCurrency: "EUR", active: true },
      { id: "card", name: "Travel card", defaultCurrency: "USD", active: true },
    ]);
    vi.spyOn(api.imports, "list").mockResolvedValue([]);
    renderPage();

    const destination = await screen.findByLabelText("Destination account");
    expect(screen.getByRole("option", { name: /Manual/ })).toBeInTheDocument();
    expect(destination).toHaveTextContent("Household cash");
    expect(destination).toHaveTextContent("Everyday account");
    expect(destination).toHaveTextContent("Travel card");
    expect(screen.getByLabelText("Statement file").getAttribute("accept")).toContain(".csv");
    expect(screen.getByLabelText("Statement file").getAttribute("accept")).toContain(".xls");
    expect(screen.getByLabelText("Statement file").getAttribute("accept")).toContain(".xlsx");
    expect(screen.getByText("Choose file")).toBeInTheDocument();
  });

  it("creates and selects an account inline", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.accounts, "list")
      .mockResolvedValueOnce([{ id: "unknown", name: "Unknown", defaultCurrency: "EUR", active: true }])
      .mockResolvedValue([
        { id: "unknown", name: "Unknown", defaultCurrency: "EUR", active: true },
        { id: "fresh", name: "Fresh", defaultCurrency: "USD", active: true },
      ]);
    vi.spyOn(api.imports, "list").mockResolvedValue([]);
    const create = vi.spyOn(api.accounts, "create").mockResolvedValue({ id: "fresh", name: "Fresh", defaultCurrency: "USD", active: true });
    renderPage();

    await user.selectOptions(await screen.findByLabelText("Destination account"), "__create__");
    const dialog = screen.getByRole("dialog", { name: "Create new account" });
    await user.type(screen.getByLabelText("Account name"), "Fresh");
    await user.clear(screen.getByLabelText("Default currency"));
    await user.type(screen.getByLabelText("Default currency"), "usd");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(create).toHaveBeenCalledWith({ name: "Fresh", defaultCurrency: "USD" });
    expect(dialog).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Destination account")).toHaveValue("fresh");
  });

  it("links committed import history to its audit rows", async () => {
    vi.spyOn(api.accounts, "list").mockResolvedValue([]);
    vi.spyOn(api.imports, "list").mockResolvedValue([{ ...batch, status: "COMMITTED" }]);
    renderPage();
    expect(await screen.findByRole("link", { name: "View audit rows" })).toHaveAttribute("href", "/imports/batch-1");
    expect(screen.queryByRole("button", { name: "Show ignored" })).not.toBeInTheDocument();
  });
});
