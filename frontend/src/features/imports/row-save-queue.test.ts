import type { StagedTransaction } from "../../api/types";
import { RowSaveQueue } from "./row-save-queue";

const savedRow = (revision: number, patch: Partial<StagedTransaction> = {}): StagedTransaction => ({
  id: "row-1",
  rowNumber: 1,
  revision,
  date: "2026-08-09",
  description: "Coffee",
  amountMinor: -500,
  currency: "SGD",
  kind: "EXPENSE",
  categoryId: null,
  subcategoryId: null,
  predictedCategoryId: null,
  predictedSubcategoryId: null,
  confidence: null,
  duplicateState: "NONE",
  duplicateExplanation: null,
  duplicateCandidate: null,
  disposition: "PENDING",
  ignoreReason: null,
  rememberCorrection: false,
  needsReview: true,
  errors: [],
  raw: {},
  normalized: {},
  ...patch,
});

describe("RowSaveQueue", () => {
  it("serializes rapid changes and advances the expected revision", async () => {
    let releaseFirst: ((row: StagedTransaction) => void) | undefined;
    const first = new Promise<StagedTransaction>((resolve) => { releaseFirst = resolve; });
    const save = vi.fn()
      .mockImplementationOnce(() => first)
      .mockResolvedValueOnce(savedRow(4, { categoryId: "food", subcategoryId: "cafes" }));
    const queue = new RowSaveQueue({
      save,
      onSaved: vi.fn(),
      onState: vi.fn(),
      onConflict: vi.fn(),
    });

    queue.enqueue("row-1", 2, { categoryId: "food" });
    queue.enqueue("row-1", 2, { subcategoryId: "cafes" });
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0]?.[0]).toMatchObject({ expectedRevision: 2, categoryId: "food", subcategoryId: null });

    releaseFirst?.(savedRow(3, { categoryId: "food" }));
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]?.[0]).toMatchObject({ expectedRevision: 3, subcategoryId: "cafes" });
  });

  it("clears a queued subcategory when a later category wins", async () => {
    let releaseFirst: ((row: StagedTransaction) => void) | undefined;
    const first = new Promise<StagedTransaction>((resolve) => { releaseFirst = resolve; });
    const save = vi.fn().mockImplementationOnce(() => first).mockResolvedValueOnce(savedRow(4));
    const queue = new RowSaveQueue({ save, onSaved: vi.fn(), onState: vi.fn(), onConflict: vi.fn() });

    queue.enqueue("row-1", 1, { categoryId: "food" });
    queue.enqueue("row-1", 1, { subcategoryId: "cafes" });
    queue.enqueue("row-1", 1, { categoryId: "travel" });
    releaseFirst?.(savedRow(2, { categoryId: "food" }));

    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]?.[0]).toMatchObject({ expectedRevision: 2, categoryId: "travel", subcategoryId: null });
  });
});
