import type { ImportExecutionPlan, ImportInspection, MappingOrigin } from "../../api/types";
import { isIso4217Currency } from "../../shared/currencies";

const aliases: Record<string, string[]> = {
  date: ["transaction date", "date", "booking date", "value date", "datum", "datum transakcije", "datum knjiženja", "datum bremenitve", "transaction timestamp", "timestamp", "completed date", "started date", "created at", "datetime", "date time"],
  description: ["description", "details", "merchant", "payee", "recipient", "opis", "memo", "narrative", "prejemnik", "prodajno mesto"],
  amount: ["amount", "transaction amount", "value", "net amount", "znesek"],
  debit: ["debit", "debit amount", "charge", "withdrawal", "breme", "odhodki"],
  credit: ["credit", "credit amount", "payment", "deposit", "dobro", "prilivi"],
  currency: ["currency", "currency code", "ccy", "valuta"],
  id: ["transaction id", "id", "reference", "native id", "referenca", "id transakcije"],
  category: ["category", "source category", "kategorija"],
  subcategory: ["subcategory", "source subcategory", "podkategorija"],
};

const numberFormat = { decimalSeparator: "." as const, thousandsSeparator: null, stripCurrencySymbols: true, allowParentheses: false, allowTrailingMinus: false };
const defaultDateFormat = "%Y-%m-%d";

export const dateFormatSuggestions = [
  defaultDateFormat,
  "%d/%m/%Y",
  "%m/%d/%Y",
  "%d.%m.%Y",
  "%Y/%m/%d",
  "%Y-%m-%d %H:%M:%S",
  "%Y-%m-%dT%H:%M:%S",
  "%Y-%m-%dT%H:%M:%S%z",
] as const;

function match(inspection: ImportInspection, target: keyof typeof aliases, inferred?: string) {
  return inspection.columns.find((column) => aliases[target]?.includes(column.normalizedLabel))?.id
    ?? inspection.columns.find((column) => column.inferredType === inferred)?.id
    ?? "";
}

export function createManualPlan(inspection: ImportInspection, defaultCurrency = ""): ImportExecutionPlan {
  const date = match(inspection, "date", "DATE")
    || inspection.columns.find((column) => column.inferredType === "TIMESTAMP")?.id
    || "";
  const signed = match(inspection, "amount", "NUMBER");
  const debit = match(inspection, "debit");
  const credit = match(inspection, "credit");
  const currency = match(inspection, "currency", "CURRENCY");
  return {
    planType: "universal", schemaVersion: inspection.executionSchemaVersion || "universal-v1",
    transactionDate: date ? { sourceColumn: date, format: inferDateFormat(inspection, date) } : null,
    transactionTimestamp: null,
    description: { sourceColumn: match(inspection, "description", "TEXT"), strip: true, collapseWhitespace: true },
    amount: !signed && debit && credit
      ? { kind: "debit_credit", debitColumn: debit, creditColumn: credit, numberFormat, debitSourceSign: "positive", creditSourceSign: "positive" }
      : { kind: "signed", sourceColumn: signed, numberFormat, signConvention: "EXPENSES_NEGATIVE" },
    currency: currency ? { kind: "source", sourceColumn: currency } : { kind: "constant", value: defaultCurrency.toUpperCase() },
    sourceNativeId: optional(match(inspection, "id")), categoryHint: optional(match(inspection, "category")), subcategoryHint: optional(match(inspection, "subcategory")),
    rowBounds: { firstRow: null, lastRow: null }, exactFilters: [], skipEmptyRows: true, skipRepeatedHeaders: true, footerRule: null,
  };
}

export function universalPlan(plan: ImportExecutionPlan | null, inspection: ImportInspection, defaultCurrency: string): ImportExecutionPlan {
  return plan ?? createManualPlan(inspection, defaultCurrency);
}

export function mappingOriginLabel(origin: MappingOrigin | null) {
  if (origin === "LLM_CONFIRMED") return "OpenAI suggestion";
  return "Manual mapping";
}

export function inferDateFormat(inspection: ImportInspection, sourceColumn: string): string {
  for (const row of inspection.preview) {
    const sample = String(row.values[sourceColumn] ?? "").trim();
    if (!sample) continue;
    const inferred = formatFromSample(sample);
    if (inferred) return inferred;
  }
  return defaultDateFormat;
}

export function mappingErrors(plan: ImportExecutionPlan): string[] {
  const errors: string[] = [];
  if (!plan.transactionDate?.sourceColumn && !plan.transactionTimestamp?.sourceColumn) errors.push("Map a date or datetime column.");
  if (plan.transactionDate && !plan.transactionDate.format.trim()) errors.push("Enter an explicit date format.");
  if (plan.transactionTimestamp && !plan.transactionTimestamp.format.trim()) errors.push("Enter an explicit timestamp format.");
  if (plan.transactionTimestamp && !plan.transactionTimestamp.timezone.trim()) errors.push("Enter a timestamp timezone.");
  if (!plan.description.sourceColumn) errors.push("Map a description column.");
  if (plan.amount.kind === "signed" && !plan.amount.sourceColumn) errors.push("Map an amount column.");
  if (plan.amount.kind === "debit_credit" && (!plan.amount.debitColumn || !plan.amount.creditColumn || plan.amount.debitColumn === plan.amount.creditColumn)) errors.push("Map different debit and credit columns.");
  if (plan.currency.kind === "source" && !plan.currency.sourceColumn) errors.push("Map a currency column or use a constant.");
  if (plan.currency.kind === "constant" && !isIso4217Currency(plan.currency.value)) errors.push("Enter a valid ISO 4217 currency constant.");
  if (plan.subcategoryHint && !plan.categoryHint) errors.push("A subcategory hint requires a category hint.");
  if (plan.rowBounds.firstRow !== null && plan.rowBounds.lastRow !== null && plan.rowBounds.firstRow > plan.rowBounds.lastRow) errors.push("The first source row must not follow the last source row.");
  if (plan.exactFilters.some((filter) => !filter.sourceColumn || filter.values.length === 0)) errors.push("Each exact filter needs a source column and at least one value.");
  if (plan.footerRule && (!plan.footerRule.sourceColumn || !plan.footerRule.normalizedValue.trim())) errors.push("A footer rule needs a source column and exact marker.");
  return errors;
}

function optional(sourceColumn: string) {
  return sourceColumn ? { sourceColumn } : null;
}

function formatFromSample(sample: string): string | null {
  const match = sample.match(/^(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})(.*)$/);
  if (!match) return null;

  const first = match[1]!;
  const separator = match[2]!;
  const second = match[3]!;
  const third = match[4]!;
  const suffix = match[5]!;
  let dateFormat: string | null = null;
  if (first.length === 4) dateFormat = `%Y${separator}%m${separator}%d`;
  else if (third.length === 4 && Number(first) > 12) dateFormat = `%d${separator}%m${separator}%Y`;
  else if (third.length === 4 && Number(second) > 12) dateFormat = `%m${separator}%d${separator}%Y`;
  if (!dateFormat) return null;
  if (!suffix) return dateFormat;

  const time = suffix.match(/^([ T])(\d{1,2}):(\d{2})(?::(\d{2}))?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/);
  if (!time) return null;
  const [, separatorBeforeTime, , , seconds, fraction, timezone] = time;
  return `${dateFormat}${separatorBeforeTime}%H:%M${seconds ? ":%S" : ""}${fraction ? ".%f" : ""}${timezone ? "%z" : ""}`;
}
