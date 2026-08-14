import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { api } from "../api/client";
import type { TaggingModel } from "../api/types";
import CategoriesPage from "./CategoriesPage";

const activeModel: TaggingModel = {
  modelVersionId: "model-active",
  modelName: "tagger-active",
  status: "ACTIVE",
  createdAt: "2026-08-13T12:00:00Z",
  activatedAt: "2026-08-13T12:01:00Z",
  trainingRowCount: 70,
  categoryCount: 4,
  subcategoryModelCount: 1,
  subcategoryConstantCount: 2,
  categoryThreshold: 0.7,
  subcategoryThreshold: 0.8,
  evaluationSchemaVersion: "grouped-hierarchy-v1",
  trainingDataChecksum: "old-snapshot",
  taxonomyCurrent: true,
  crossValidation: {
    requestedFolds: 5,
    effectiveFolds: 3,
    evaluatedRowCount: 70,
    categoryAccuracy: 0.9,
    exactMatchAccuracy: 0.82,
    autoAcceptCoverage: 0.68,
    autoAcceptAccuracy: 0.94,
  },
};

const candidateModel: TaggingModel = {
  ...activeModel,
  modelVersionId: "model-candidate",
  modelName: "tagger-candidate",
  status: "CANDIDATE",
  createdAt: "2026-08-14T12:00:00Z",
  activatedAt: null,
  trainingRowCount: 75,
  trainingDataChecksum: "new-snapshot",
  crossValidation: {
    requestedFolds: 5,
    effectiveFolds: 3,
    evaluatedRowCount: 75,
    categoryAccuracy: 0.92,
    exactMatchAccuracy: 0.84,
    autoAcceptCoverage: 0.72,
    autoAcceptAccuracy: 0.96,
  },
};

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

  it("compares a candidate and activates it only after review", async () => {
    const user = userEvent.setup();
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);
    vi.spyOn(api.accounts, "list").mockResolvedValue([]);
    vi.spyOn(api.tagRules, "list").mockResolvedValue([]);
    vi.spyOn(api.taggingModels, "overview")
      .mockResolvedValueOnce({ active: activeModel, candidate: null, previous: null })
      .mockResolvedValueOnce({ active: activeModel, candidate: candidateModel, previous: null })
      .mockResolvedValueOnce({ active: { ...candidateModel, status: "ACTIVE", activatedAt: "2026-08-14T12:05:00Z" }, candidate: null, previous: { ...activeModel, status: "PREVIOUS" } });
    vi.spyOn(api.taggingModels, "retrain").mockResolvedValue(candidateModel);
    vi.spyOn(api.taggingModels, "activate").mockResolvedValue({ ...candidateModel, status: "ACTIVE", activatedAt: "2026-08-14T12:05:00Z" });
    render(<MemoryRouter><CategoriesPage /></MemoryRouter>);

    await user.click(screen.getByRole("button", { name: /Model training/ }));
    expect(await screen.findByText("Active cross-validation results")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Train candidate" }));

    expect(await screen.findByText("Candidate trained. Compare its results before activation.")).toBeInTheDocument();
    expect(await screen.findByText(/Exact-match accuracy is.*better/)).toBeInTheDocument();
    expect(screen.getAllByText("+2 pp")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Candidate awaiting review" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Activate candidate" }));

    expect(api.taggingModels.retrain).toHaveBeenCalledOnce();
    expect(api.taggingModels.activate).toHaveBeenCalledWith("model-candidate");
    expect(await screen.findByText("Candidate activated. The replaced model is available for rollback.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Restore previous" })).toBeInTheDocument();
  });

  it("requires confirmation before activating a regressed candidate", async () => {
    const user = userEvent.setup();
    const regressed = {
      ...candidateModel,
      crossValidation: {
        ...candidateModel.crossValidation!,
        exactMatchAccuracy: 0.78,
      },
    };
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);
    vi.spyOn(api.accounts, "list").mockResolvedValue([]);
    vi.spyOn(api.tagRules, "list").mockResolvedValue([]);
    vi.spyOn(api.taggingModels, "overview").mockResolvedValue({ active: activeModel, candidate: regressed, previous: null });
    vi.spyOn(api.taggingModels, "activate").mockResolvedValue({ ...regressed, status: "ACTIVE", activatedAt: "2026-08-14T12:05:00Z" });
    const confirmation = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<MemoryRouter><CategoriesPage /></MemoryRouter>);

    await user.click(screen.getByRole("button", { name: /Model training/ }));
    expect(await screen.findByText(/Exact-match accuracy is.*worse/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Activate candidate" }));
    expect(confirmation).toHaveBeenCalledOnce();
    expect(api.taggingModels.activate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Activate candidate" }));
    expect(api.taggingModels.activate).toHaveBeenCalledWith("model-candidate");
  });
});
