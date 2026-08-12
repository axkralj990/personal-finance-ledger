export function formatMoney(amountMinor: number | null | undefined, currency: string | null | undefined, locale = "en-SG"): string {
  if (amountMinor === null || amountMinor === undefined) return "Amount unavailable";
  if (!currency) return "Currency unavailable";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amountMinor / 100);
  } catch {
    return `${currency} ${(amountMinor / 100).toFixed(2)}`;
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Date unavailable";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("en-SG", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

export function parseMajorAmount(value: string): number | null {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d{1,2}))?$/);
  if (!match) return null;
  const [, sign, major = "", fraction = ""] = match;
  const minor = Number(major) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(minor)) return null;
  return sign === "-" ? -minor : minor;
}

export function minorToMajorInput(amountMinor: number): string {
  const sign = amountMinor < 0 ? "-" : "";
  const absolute = Math.abs(amountMinor);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

export function localCalendarDate(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
