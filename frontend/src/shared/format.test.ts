import { localCalendarDate, formatMoney, minorToMajorInput, parseMajorAmount } from "./format";

describe("formatMoney", () => {
  it("formats integer minor units with a currency and decimals", () => {
    const formatted = formatMoney(123456, "SGD", "en-SG");
    expect(formatted).toContain("1,234.56");
    expect(formatted).toMatch(/SGD|\$/);
  });

  it("refuses to imply a total without a currency", () => {
    expect(formatMoney(1000, "")).toBe("Currency unavailable");
    expect(formatMoney(null, "SGD")).toBe("Amount unavailable");
  });

  it("converts signed major-unit input to minor units", () => {
    expect(parseMajorAmount("-24.90")).toBe(-2490);
    expect(parseMajorAmount("0.29")).toBe(29);
    expect(parseMajorAmount("12.3")).toBe(1230);
    expect(parseMajorAmount("1.005")).toBeNull();
    expect(parseMajorAmount("1e2")).toBeNull();
    expect(parseMajorAmount("not money")).toBeNull();
    expect(minorToMajorInput(-2490)).toBe("-24.90");
    expect(minorToMajorInput(29)).toBe("0.29");
  });

  it("formats a local calendar date without UTC conversion", () => {
    expect(localCalendarDate(new Date(2026, 0, 2, 23, 30))).toBe("2026-01-02");
  });
});
