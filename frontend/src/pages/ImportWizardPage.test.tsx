import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import batchJson from "../test/fixtures/import-batch.json";
import inspectionJson from "../test/fixtures/import-inspection.json";
import previewJson from "../test/fixtures/mapping-preview.json";
import fallbackJson from "../test/fixtures/mapping-suggestion-fallback.json";
import successJson from "../test/fixtures/mapping-suggestion-success.json";
import { api } from "../api/client";
import {
  mapImportBatch,
  mapImportInspection,
  mapMappingPreview,
  mapMappingSuggestion,
} from "../api/mappers";
import type { ImportBatch, MappingPreview } from "../api/types";
import ImportWizardPage from "./ImportWizardPage";

const inspected = mapImportInspection(inspectionJson);
const mappedPreview = mapMappingPreview(previewJson);

function batch(
  status: ImportBatch["status"] = "AWAITING_MAPPING",
  current = false,
): ImportBatch {
  return mapImportBatch({
    ...batchJson,
    status,
    revision: status === "READY" ? 7 : 3,
    mapping_revision: current || status === "READY" ? 2 : 0,
    included_rows: status === "READY" ? 26 : 0,
    current_mapping_origin:
      current || status === "READY" ? batchJson.current_mapping_origin : null,
    current_execution_plan:
      current || status === "READY" ? batchJson.current_execution_plan : null,
    source_mapping_template_id:
      current || status === "READY"
        ? batchJson.source_mapping_template_id
        : null,
    source_mapping_template_version_id:
      current || status === "READY"
        ? batchJson.source_mapping_template_version_id
        : null,
  });
}

function validPreview(): MappingPreview {
  return {
    ...mappedPreview,
    importableRows: 29,
    errorRows: 0,
    rows: [{ ...mappedPreview.rows[0]!, rowNumber: 2, errors: [] }],
  };
}

function prepare(
  status: ImportBatch["status"] = "AWAITING_MAPPING",
  current = false,
) {
  vi.spyOn(api.imports, "detail").mockResolvedValue(batch(status, current));
  vi.spyOn(api.imports, "inspection").mockResolvedValue(inspected);
  vi.spyOn(api.importMappings, "list").mockResolvedValue([]);
  vi.spyOn(api.accounts, "list").mockResolvedValue([
    {
      id: "account-1",
      name: "Everyday account",
      defaultCurrency: "EUR",
      active: true,
    },
  ]);
}

function renderWizard(path = "/imports/batch-1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/imports/:id" element={<ImportWizardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ImportWizardPage", () => {
  it("patches sheet changes immediately, reloads preview revision, and pages raw rows", async () => {
    const user = userEvent.setup();
    prepare();
    vi.mocked(api.imports.detail)
      .mockResolvedValueOnce(batch())
      .mockResolvedValue({ ...batch(), revision: 4 });
    const changed = mapImportInspection({
      ...inspectionJson,
      revision: 4,
      inspection: {
        ...inspectionJson.inspection,
        selected_sheet: "Archive",
        header_row: 2,
        preview_offset: 0,
      },
    });
    const patch = vi
      .spyOn(api.imports, "patchInspection")
      .mockResolvedValue(changed);
    renderWizard();
    await user.selectOptions(await screen.findByLabelText("Sheet"), "Archive");
    expect(patch).toHaveBeenCalledWith(
      "batch-1",
      expect.objectContaining({
        expectedRevision: 3,
        selectedSheet: "Archive",
        headerRow: 2,
        previewOffset: 0,
        previewLimit: 25,
      }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Header row")).toHaveValue(2),
    );
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(api.imports.inspection).toHaveBeenLastCalledWith("batch-1", {
        offset: 25,
        limit: 25,
      }),
    );
  });

  it("defaults to the backend inferred universal mapping before templates and manual", async () => {
    prepare();
    vi.spyOn(api.imports, "previewMapping").mockResolvedValue(validPreview());
    renderWizard("/imports/batch-1?step=map");
    expect(
      await screen.findByRole("radio", { name: /Inferred universal mapping/ }),
    ).toBeChecked();
    expect(screen.getByRole("radio", { name: /Account card/ })).not.toBeChecked();
    expect(
      screen.getByRole("radio", { name: /Global card/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /Blank editable mapping/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/profile/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Expense sign convention")).toHaveValue("EXPENSES_POSITIVE");
    expect(screen.getByLabelText("Date format")).toHaveAttribute(
      "list",
      "mapping-date-formats",
    );
    expect(screen.queryByLabelText(/day first/i)).not.toBeInTheDocument();
  });

  it("allows explicit formats to be edited and blocks blank formats", async () => {
    const user = userEvent.setup();
    prepare();
    const preview = vi.spyOn(api.imports, "previewMapping").mockResolvedValue(validPreview());
    renderWizard("/imports/batch-1?step=map");
    const format = await screen.findByLabelText("Date format");
    await user.clear(format);
    expect(await screen.findByText("Enter an explicit date format.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm mapping and stage rows" })).toBeDisabled();
    await user.type(format, "%d/%m/%Y");
    await waitFor(() =>
      expect(preview).toHaveBeenLastCalledWith(
        "batch-1",
        expect.objectContaining({
          transactionDate: { sourceColumn: "c000", format: "%d/%m/%Y" },
        }),
        expect.anything(),
      ),
    );
  });

  it("detaches a selected template when edited and stages with the latest confirmation", async () => {
    const user = userEvent.setup();
    prepare();
    vi.spyOn(api.imports, "previewMapping").mockResolvedValue(validPreview());
    const confirm = vi
      .spyOn(api.imports, "confirmMapping")
      .mockResolvedValue({
        batchId: "batch-1",
        revision: 4,
        mappingRevision: 1,
        plan: inspected.proposals.templates[0]!.plan,
      });
    const stage = vi
      .spyOn(api.imports, "stage")
      .mockResolvedValue(batch("STAGING"));
    renderWizard("/imports/batch-1?step=map");
    await user.click(await screen.findByRole("radio", { name: /Account card/ }));
    await user.selectOptions(
      screen.getByLabelText("Expense sign convention"),
      "EXPENSES_POSITIVE",
    );
    const action = await screen.findByRole("button", {
      name: "Confirm mapping and stage rows",
    });
    await waitFor(() => expect(action).toBeEnabled());
    await user.click(action);
    expect(confirm).toHaveBeenCalledWith(
      "batch-1",
      expect.objectContaining({
        expectedRevision: 3,
        templateId: undefined,
        templateVersionId: undefined,
      }),
    );
    expect(stage).toHaveBeenCalledWith("batch-1", 4, 1);
  });

  it.each([
    ["success", successJson],
    ["fallback", fallbackJson],
  ])(
    "uses the suggestion response revision after %s",
    async (_case, response) => {
      const user = userEvent.setup();
      prepare();
      vi.spyOn(api.imports, "previewMapping").mockResolvedValue(validPreview());
      vi.spyOn(api.imports, "mappingSuggestionPayload").mockResolvedValue({
        payload: { columns: [{ header: "Sensitive header" }] },
        digest: "d".repeat(64),
        revision: 3,
      });
      vi.spyOn(api.imports, "suggestMapping").mockResolvedValue(
        mapMappingSuggestion(response),
      );
      const confirm = vi
        .spyOn(api.imports, "confirmMapping")
        .mockResolvedValue({
          batchId: "batch-1",
          revision: 5,
          mappingRevision: 1,
          plan: inspected.proposals.templates[0]!.plan,
        });
      vi.spyOn(api.imports, "stage").mockResolvedValue(batch("STAGING"));
      renderWizard("/imports/batch-1?step=map");
      await user.click(
        await screen.findByRole("button", {
          name: "Suggest mapping with OpenAI",
        }),
      );
      await user.click(screen.getByLabelText(/I reviewed this exact payload/));
      await user.click(
        screen.getByRole("button", { name: "Consent and request suggestion" }),
      );
      if (_case === "fallback")
        await user.selectOptions(
          screen.getByLabelText("Expense sign convention"),
          "EXPENSES_POSITIVE",
        );
      const action = await screen.findByRole("button", {
        name: "Confirm mapping and stage rows",
      });
      await waitFor(() => expect(action).toBeEnabled());
      await user.click(action);
      expect(confirm).toHaveBeenCalledWith(
        "batch-1",
        expect.objectContaining({ expectedRevision: 4 }),
      );
    },
  );

  it("recovers the confirmed immutable plan and renders only the remap body", async () => {
    prepare("READY", true);
    vi.spyOn(api.imports, "previewMapping").mockResolvedValue(validPreview());
    renderWizard("/imports/batch-1?step=map&remap=1");
    expect(
      await screen.findByRole("radio", {
        name: /Confirmed mapping revision 2/,
      }),
    ).toBeChecked();
    expect(screen.getByLabelText("Date format")).toHaveValue("%Y-%m-%d");
    expect(
      screen.queryByRole("heading", { name: /Commit 26 accepted rows/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Review staged rows" }),
    ).not.toBeInTheDocument();
  });

  it("offers inspection remap and uses exact backend commit counts", async () => {
    const user = userEvent.setup();
    prepare("READY", true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWizard();
    expect(
      await screen.findByRole("heading", { name: "Commit 26 accepted rows" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Audit only").nextElementSibling).toHaveTextContent(
      "2",
    );
    await user.click(
      screen.getByRole("button", { name: "Change sheet or header" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Inspect source table" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Commit 26 accepted rows/ }),
    ).not.toBeInTheDocument();
  });

  it("pages mapping preview and displays row errors beyond the first 25 rows", async () => {
    const user = userEvent.setup();
    prepare();
    const first = validPreview();
    const preview = vi
      .spyOn(api.imports, "previewMapping")
      .mockResolvedValueOnce(first)
      .mockResolvedValue(mappedPreview);
    renderWizard("/imports/batch-1?step=map");
    const next = await screen.findByRole("button", { name: "Next" });
    await waitFor(() => expect(next).toBeEnabled());
    await user.click(next);
    await waitFor(() =>
      expect(preview).toHaveBeenLastCalledWith("batch-1", expect.anything(), {
        offset: 25,
        limit: 25,
      }),
    );
    expect(
      await screen.findByText("Date could not be parsed"),
    ).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /27.*Late row/ })).toHaveClass(
      "preview-error",
    );
  });

  it("retries a failed inspection with an explicit reload", async () => {
    const user = userEvent.setup();
    prepare();
    vi.mocked(api.imports.inspection)
      .mockRejectedValueOnce(new Error("Inspection temporarily unavailable."))
      .mockResolvedValue(inspected);
    renderWizard();
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Inspect source table" })).toBeInTheDocument();
    expect(api.imports.inspection).toHaveBeenCalledTimes(2);
  });

  it("shows committed import rows including ignored rows as immutable audit data", async () => {
    prepare("COMMITTED", true);
    vi.spyOn(api.imports, "rows").mockResolvedValue([
      {
        id: "row-ignored", rowNumber: 2, revision: 3, date: "2026-08-01",
        description: "Ignored merchant", amountMinor: -450, currency: "EUR", kind: "EXPENSE",
        categoryId: null, subcategoryId: null, predictedCategoryId: null,
        predictedSubcategoryId: null, confidence: null, duplicateState: "NONE",
        duplicateExplanation: null, duplicateCandidate: null, disposition: "IGNORE",
        ignoreReason: "USER_IGNORED", rememberCorrection: false, needsReview: false,
        errors: [], raw: { c001: "Ignored merchant" }, normalized: {},
      },
    ]);
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue([]);
    renderWizard();
    expect(await screen.findByText("Ignored merchant")).toBeInTheDocument();
    expect(screen.getByText(/Audit rows are read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remap columns" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ignore selected" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Commit accepted rows" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show ignored" })).not.toBeInTheDocument();
  });
});
