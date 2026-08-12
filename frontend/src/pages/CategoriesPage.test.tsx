import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { api } from "../api/client";
import CategoriesPage from "./CategoriesPage";

describe("CategoriesPage failures", () => {
  it("retains create drafts and rename state when requests fail", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([{ id: "food", name: "Food", sortOrder: 1, active: true, subcategories: [] }]);
    vi.spyOn(api.tagRules, "list").mockResolvedValue([]);
    vi.spyOn(api.taxonomy, "createCategory").mockRejectedValue(new Error("Create failed"));
    vi.spyOn(api.taxonomy, "patchCategory").mockRejectedValue(new Error("Rename failed"));
    render(<MemoryRouter><CategoriesPage /></MemoryRouter>);

    const draft = await screen.findByLabelText("New parent category");
    await user.type(draft, "Travel");
    await user.click(screen.getByRole("button", { name: /Add category/ }));
    expect(await screen.findByText("Create failed")).toBeInTheDocument();
    expect(draft).toHaveValue("Travel");

    await user.click(screen.getByRole("button", { name: /Rename/ }));
    const rename = screen.getByLabelText("Rename Food");
    await user.clear(rename);
    await user.type(rename, "Dining");
    await user.click(screen.getByRole("button", { name: "Save name" }));
    expect(await screen.findByText("Rename failed")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Dining")).toBeInTheDocument();
  });
});
