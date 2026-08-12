const sourceConfigs = {
  REVOLUT: { accept: ".csv,text/csv", help: "Upload the original Revolut CSV export." },
  DBS: { accept: ".xls,.xlsx,.csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv", help: "Upload a DBS XLS, XLSX, or CSV export." },
  MASTERCARD: { accept: ".xls,.xlsx,.csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv", help: "Upload the original Mastercard XLS, XLSX, or CSV export." },
} as const;

export const supportedImportProviders = new Set(Object.keys(sourceConfigs));

export function importSourceConfig(provider: string) {
  return sourceConfigs[provider.toUpperCase() as keyof typeof sourceConfigs] ?? null;
}
