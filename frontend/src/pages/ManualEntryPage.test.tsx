import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { api } from "../api/client";
import { manualRowError } from "../features/manual-input";
import ManualEntryPage from "./ManualEntryPage";

describe("ManualEntryPage taxonomy", () => {
  it("validates signed amounts without special handling", () => {
    const base = { id: "row", sourceAccountId: "a", date: "2026-08-09", description: "Pay", amount: "10.00", currency: "SGD", categoryId: "", subcategoryId: "" };
    expect(manualRowError(base)).toBeNull();
    expect(manualRowError({ ...base, amount: "-10.001" })).toMatch(/at most two decimal places/);
    expect(manualRowError({ ...base, amount: "-10.00" })).toBeNull();
    expect(manualRowError({ ...base, amount: "0.00" })).toBe("Amount cannot be zero.");
  });

  it("changes the available subcategories with the parent category", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([{ id: "a", provider: "Manual", displayName: "Cash", defaultCurrency: "SGD", active: true }]);
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([
      { id: "food", name: "Food", sortOrder: 1, active: true, subcategories: [{ id: "cafes", categoryId: "food", name: "Cafes", sortOrder: 1, active: true }] },
      { id: "home", name: "Home", sortOrder: 2, active: true, subcategories: [{ id: "rent", categoryId: "home", name: "Rent", sortOrder: 1, active: true }] },
    ]);
    render(<MemoryRouter><ManualEntryPage /></MemoryRouter>);

    const category = await screen.findByLabelText("Category");
    expect(screen.queryByLabelText("Special handling")).not.toBeInTheDocument();
    const subcategory = screen.getByLabelText("Subcategory");
    await user.selectOptions(category, "food");
    expect(screen.getByRole("option", { name: "Cafes" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Rent" })).not.toBeInTheDocument();
    await user.selectOptions(category, "home");
    expect(screen.getByRole("option", { name: "Rent" })).toBeInTheDocument();
    expect(subcategory).toHaveValue("");
  });

  it("renders the bulk date editor without an unregistered-module error", async () => {
    const user = userEvent.setup();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(api.sourceAccounts, "list").mockResolvedValue([{ id: "a", provider: "Manual", displayName: "Cash", defaultCurrency: "SGD", active: true }]);
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);

    render(<MemoryRouter><ManualEntryPage /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Bulk" }));
    await screen.findByText("Bulk draft");

    await waitFor(() => {
      const messages = consoleError.mock.calls.flat().join(" ");
      expect(messages).not.toContain("AG Grid #200");
      expect(messages).not.toContain("DateEditorModule");
    });
    consoleError.mockRestore();
  });
});
