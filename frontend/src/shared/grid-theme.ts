import {
  CellStyleModule,
  ClientSideRowModelModule,
  DateEditorModule,
  ModuleRegistry,
  RowSelectionModule,
  SelectEditorModule,
  TextEditorModule,
  ValidationModule,
  themeQuartz,
} from "ag-grid-community";

ModuleRegistry.registerModules([
  ClientSideRowModelModule,
  DateEditorModule,
  RowSelectionModule,
  SelectEditorModule,
  TextEditorModule,
  CellStyleModule,
  ValidationModule,
]);

export const ledgerGridTheme = themeQuartz.withParams({
  accentColor: "#315b45",
  backgroundColor: "#fbf8f0",
  foregroundColor: "#272923",
  borderColor: "#d8d1c2",
  headerBackgroundColor: "#ebe5d8",
  headerTextColor: "#55584f",
  oddRowBackgroundColor: "#f7f2e8",
  selectedRowBackgroundColor: "rgba(49, 91, 69, 0.12)",
  rowHoverColor: "rgba(49, 91, 69, 0.07)",
  fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, sans-serif",
  fontSize: 13,
  dataFontSize: 13,
  headerFontSize: 11,
  headerFontWeight: 600,
  borderRadius: 0,
  wrapperBorderRadius: 0,
  spacing: 7,
  rowBorder: { color: "#e5ded0", style: "solid", width: 1 },
  columnBorder: false,
});
