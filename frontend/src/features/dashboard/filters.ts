import { localCalendarDate } from "../../shared/format";

export interface DashboardUrlFilters {
  dateFrom: string;
  dateTo: string;
  categoryIds: string[];
  subcategoryIds: string[];
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function getDefaultDashboardDates(today = new Date()): Pick<DashboardUrlFilters, "dateFrom" | "dateTo"> {
  const year = today.getFullYear() - 1;
  const month = today.getMonth();
  const day = Math.min(today.getDate(), new Date(year, month + 1, 0).getDate());
  return {
    dateFrom: localCalendarDate(new Date(year, month, day)),
    dateTo: localCalendarDate(today),
  };
}

export function readDashboardFilters(params: URLSearchParams, today = new Date()): DashboardUrlFilters {
  const defaults = getDefaultDashboardDates(today);
  return {
    dateFrom: params.get("date_from") ?? defaults.dateFrom,
    dateTo: params.get("date_to") ?? defaults.dateTo,
    categoryIds: params.getAll("category_id").filter(Boolean),
    subcategoryIds: params.getAll("subcategory_id").filter(Boolean),
  };
}

export function dashboardDateError(filters: DashboardUrlFilters): string | null {
  if (!isCalendarDate(filters.dateFrom) || !isCalendarDate(filters.dateTo)) {
    return "Enter valid calendar dates for the selected range.";
  }
  if (filters.dateFrom > filters.dateTo) return "From date must be on or before the to date.";
  return null;
}

export function writeDashboardFilters(filters: DashboardUrlFilters): URLSearchParams {
  const params = new URLSearchParams({ date_from: filters.dateFrom, date_to: filters.dateTo });
  filters.categoryIds.forEach((id) => params.append("category_id", id));
  filters.subcategoryIds.forEach((id) => params.append("subcategory_id", id));
  return params;
}

function isCalendarDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const [year = 0, month = 0, day = 0] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}
