import { importSourceConfig, supportedImportProviders } from "./source-config";

describe("import source configuration", () => {
  it("supports only the three statement providers with provider-specific formats", () => {
    expect([...supportedImportProviders]).toEqual(["REVOLUT", "DBS", "MASTERCARD"]);
    expect(importSourceConfig("REVOLUT")?.accept).toBe(".csv,text/csv");
    expect(importSourceConfig("DBS")?.accept).toContain(".xlsx");
    expect(importSourceConfig("MASTERCARD")?.accept).toContain(".xlsx");
    expect(importSourceConfig("MASTERCARD")?.accept).toContain(".csv");
    expect(importSourceConfig("MANUAL")).toBeNull();
  });
});
