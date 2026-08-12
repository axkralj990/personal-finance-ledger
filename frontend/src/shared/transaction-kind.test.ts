import {
  transactionKindError,
} from "./transaction-kind";

describe("transaction amount validation", () => {
  it("rejects zero amounts without kind-specific rules", () => {
    expect(transactionKindError(0)).toBe("Amount cannot be zero.");
    expect(transactionKindError(-1250)).toBeNull();
    expect(transactionKindError(1250)).toBeNull();
  });
});
