import type { ImportInspection } from "../../api/types";
import { createManualPlan, inferDateFormat, mappingErrors } from "./mapping-plan";

const inspection: ImportInspection = {
  batchRevision: 3, inspectionVersion: "inspection-v1", executionSchemaVersion: "universal-v1", fileType: "CSV", encoding: "utf-8", delimiter: ",", quoteCharacter: '"',
  sheets: [{ name: "Sheet 1", index: 0, rowCount: 3, columnCount: 4, candidateHeaderRows: [1] }], selectedSheet: "Sheet 1", headerRow: 1, dataStartRow: 2, dataEndRow: 3, rowCount: 2,
  blankRows: [], repeatedHeaderRows: [], possibleFooterRows: [], previewOffset: 0, structuralSignature: "a".repeat(64), diagnostics: [], proposals: { templates: [], universal: null },
  columns: [
    { id: "c000", position: 0, rawLabel: "Booking Date", normalizedLabel: "booking date", inferredType: "DATE" },
    { id: "c001", position: 1, rawLabel: "Memo", normalizedLabel: "memo", inferredType: "TEXT" },
    { id: "c002", position: 2, rawLabel: "Value", normalizedLabel: "value", inferredType: "NUMBER" },
    { id: "c003", position: 3, rawLabel: "Currency", normalizedLabel: "currency", inferredType: "CURRENCY" },
  ],
  preview: [{ rowNumber: 2, values: { c000: "2026-08-01", c001: "Cafe", c002: "-4.50", c003: "EUR" } }],
};

describe("universal mapping defaults", () => {
  it("uses labels and inferred types without account-specific parser configuration", () => {
    const plan = createManualPlan(inspection, "USD");
    expect(plan).toMatchObject({ transactionDate: { sourceColumn: "c000", format: "%Y-%m-%d" }, description: { sourceColumn: "c001" }, amount: { kind: "signed", sourceColumn: "c002", signConvention: "EXPENSES_NEGATIVE" }, currency: { kind: "source", sourceColumn: "c003" } });
    expect(mappingErrors(plan)).toEqual([]);
  });

  it("infers explicit date and timestamp formats from preview samples", () => {
    const preview = [
      { rowNumber: 2, values: { c000: "31/08/2026", c004: "2026-08-31T14:05:06Z" } },
    ];
    expect(inferDateFormat({ ...inspection, preview }, "c000")).toBe("%d/%m/%Y");
    expect(inferDateFormat({ ...inspection, preview }, "c004")).toBe("%Y-%m-%dT%H:%M:%S%z");
    expect(inferDateFormat({ ...inspection, preview }, "missing")).toBe("%Y-%m-%d");
  });

  it("maps a single datetime column to the transaction date", () => {
    const datetimeInspection = {
      ...inspection,
      columns: inspection.columns.map((column) => column.id === "c000"
        ? { ...column, rawLabel: "Created At", normalizedLabel: "created at", inferredType: "TIMESTAMP" as const }
        : column),
      preview: [{ rowNumber: 2, values: { ...inspection.preview[0]!.values, c000: "2026-08-01T23:30:00" } }],
    };

    const plan = createManualPlan(datetimeInspection, "USD");

    expect(plan.transactionDate).toEqual({ sourceColumn: "c000", format: "%Y-%m-%dT%H:%M:%S" });
    expect(plan.transactionTimestamp).toBeNull();
  });

  it("uses the safe standard for ambiguous dates", () => {
    const preview = [{ rowNumber: 2, values: { c000: "08/09/2026" } }];
    expect(inferDateFormat({ ...inspection, preview }, "c000")).toBe("%Y-%m-%d");
  });

  it("reports incomplete required controls", () => {
    const plan = createManualPlan({ ...inspection, columns: [] }, "");
    expect(mappingErrors(plan)).toEqual(expect.arrayContaining(["Map a date or datetime column.", "Map a description column.", "Map an amount column.", "Enter a valid ISO 4217 currency constant."]));
  });

  it("rejects three-letter values that are not ISO 4217 currencies", () => {
    const plan = createManualPlan({ ...inspection, columns: inspection.columns.filter((column) => column.id !== "c003") }, "ZZZ");
    expect(mappingErrors(plan)).toContain("Enter a valid ISO 4217 currency constant.");
  });

  it("rejects blank explicit formats and timestamp timezones", () => {
    const plan = createManualPlan(inspection, "USD");
    expect(mappingErrors({ ...plan, transactionDate: { sourceColumn: "c000", format: "  " } })).toContain("Enter an explicit date format.");
    expect(mappingErrors({ ...plan, transactionDate: null, transactionTimestamp: { sourceColumn: "c000", format: "", timezone: " " } })).toEqual(expect.arrayContaining(["Enter an explicit timestamp format.", "Enter a timestamp timezone."]));
  });
});
