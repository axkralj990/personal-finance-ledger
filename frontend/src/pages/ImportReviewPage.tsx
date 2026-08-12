import { useEffect, useRef, useState } from "react";
import type { CellEditRequestEvent, ColDef, SelectionChangedEvent } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { AlertTriangle, Check, Eye, RotateCcw } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import type { StagedTransaction } from "../api/types";
import { Drawer } from "../components/Drawer";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { RowSaveQueue, type StagedChanges } from "../features/imports/row-save-queue";
import { SerialTaskQueue } from "../features/imports/serial-task-queue";
import {
  blockedDuplicateCount,
  defaultReviewFilter,
  effectiveCategoryId,
  effectiveSubcategoryId,
  hasSuggestedLabels,
  isActionableRow,
  matchesDescriptionSearch,
  matchesReviewFilter,
  mergeSavedRow,
  reviewCount,
  selectedInclusionChanges,
  suggestionAcceptanceChanges,
  suggestedLabels,
  type ReviewFilter,
  type SaveState,
} from "../features/imports/row-state";
import { useMediaQuery } from "../hooks/use-media-query";
import { useResource } from "../hooks/use-resource";
import { formatDate, formatMoney, parseMajorAmount } from "../shared/format";
import { ledgerGridTheme } from "../shared/grid-theme";
import { categoryName, subcategoriesFor, subcategoryName } from "../shared/taxonomy";
import { transactionKindError } from "../shared/transaction-kind";

const filters: { value: ReviewFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
  { value: "LIKELY_DUPLICATE", label: "Likely duplicate" },
  { value: "INVALID", label: "Invalid" },
  { value: "IGNORED", label: "Ignored" },
];
const draftStatuses = new Set(["UPLOADED", "PARSED", "NEEDS_REVIEW", "READY"]);
const mobilePageSize = 20;
const emptyRows: StagedTransaction[] = [];

interface RepairDraft {
  date: string;
  description: string;
  amount: string;
  currency: string;
}

function SuggestedValue({ label, suggested }: { label: string; suggested: boolean }) {
  return (
    <span className="suggested-value">
      <span>{label}</span>
      {suggested && <span className="suggested-marker">Suggested</span>}
    </span>
  );
}

function applyChanges(row: StagedTransaction, changes: StagedChanges): StagedTransaction {
  return {
    ...row,
    ...(changes.transactionDate !== undefined && { date: changes.transactionDate }),
    ...(changes.description !== undefined && { description: changes.description }),
    ...(changes.amountMinor !== undefined && { amountMinor: changes.amountMinor }),
    ...(changes.currency !== undefined && { currency: changes.currency }),
    ...(changes.categoryId !== undefined && { categoryId: changes.categoryId }),
    ...(changes.subcategoryId !== undefined && { subcategoryId: changes.subcategoryId }),
    ...(changes.disposition !== undefined && { disposition: changes.disposition }),
    ...(changes.ignoreReason !== undefined && { ignoreReason: changes.ignoreReason }),
    ...(changes.rememberCorrection !== undefined && { rememberCorrection: changes.rememberCorrection }),
  };
}

function isValidCalendarDate(value: string): boolean {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

export default function ImportReviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const batch = useResource(() => api.imports.detail(id), `batch:${id}`);
  const loadedRows = useResource(() => api.imports.rows(id), `batch-rows:${id}`);
  const categories = useResource(() => api.taxonomy.categories(), "review-categories");
  const [editedRows, setEditedRows] = useState<StagedTransaction[] | null>(null);
  const [filter, setFilter] = useState<ReviewFilter | null>(null);
  const [descriptionSearch, setDescriptionSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [repair, setRepair] = useState<RepairDraft | null>(null);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [saveStates, setSaveStates] = useState<Record<string, SaveState>>({});
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [committing, setCommitting] = useState(false);
  const [mobilePage, setMobilePage] = useState(1);
  const isMobile = useMediaQuery("(max-width: 700px)");
  const taxonomy = categories.data ?? [];
  const rows = editedRows ?? loadedRows.data ?? emptyRows;
  const rowsRef = useRef(rows);
  const queueRef = useRef<RowSaveQueue | null>(null);
  const writeQueueRef = useRef(new SerialTaskQueue());

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  function replaceRows(updater: (current: StagedTransaction[]) => StagedTransaction[]) {
    const next = updater(rowsRef.current);
    rowsRef.current = next;
    setEditedRows(next);
  }

  useEffect(() => {
    queueRef.current = new RowSaveQueue({
      save: async (patch) => {
        try {
          const saved = await writeQueueRef.current.run(() => api.imports.patchRows(id, [patch]));
          const row = saved[0];
          if (!row) throw new Error("The service returned no saved row.");
          return row;
        } catch (error) {
          setActionError(error instanceof Error ? error.message : "The row could not be saved.");
          throw error;
        }
      },
      onSaved: (saved) => {
        const next = rowsRef.current.map((row) => row.id === saved.id ? mergeSavedRow(row, saved) : row);
        rowsRef.current = next;
        setEditedRows(next);
      },
      onState: (rowId, state) => {
        setSaveStates((current) => ({ ...current, [rowId]: state }));
      },
      onConflict: async (rowId, unsaved) => {
        try {
          const currentRows = await api.imports.rows(id);
          const displayRows = currentRows.map((row) => row.id === rowId ? applyChanges(row, unsaved) : row);
          rowsRef.current = displayRows;
          setEditedRows(displayRows);
          return currentRows.find((row) => row.id === rowId)?.revision ?? null;
        } catch (error) {
          setActionError(error instanceof Error ? error.message : "Current staged rows could not be reloaded.");
          return null;
        }
      },
    });
    return () => {
      queueRef.current = null;
    };
  }, [id]);

  const activeFilter = filter ?? defaultReviewFilter(rows);
  const visibleRows = rows.filter(
    (row) => matchesReviewFilter(row, activeFilter)
      && matchesDescriptionSearch(row, descriptionSearch),
  );
  const visibleIds = new Set(visibleRows.map((row) => row.id));
  const selectedVisibleRows = rows.filter((row) => selectedIds.includes(row.id) && visibleIds.has(row.id) && isActionableRow(row));
  const selectedSuggestedRows = selectedVisibleRows.filter(hasSuggestedLabels);
  const detail = rows.find((row) => row.id === detailId) ?? null;
  const unresolved = reviewCount(rows);
  const blocked = blockedDuplicateCount(rows);
  const invalid = rows.filter((row) => isActionableRow(row) && row.errors.length > 0 && row.disposition !== "IGNORE").length;
  const pendingRows = rows.filter((row) => row.disposition === "PENDING").length;
  const unsafeSaveState = rows.some((row) => ["SAVING", "ERROR", "CONFLICT"].includes(saveStates[row.id] ?? "IDLE"));
  const mobilePageCount = Math.max(1, Math.ceil(visibleRows.length / mobilePageSize));
  const activeMobilePage = Math.min(mobilePage, mobilePageCount);
  const mobileRows = visibleRows.slice((activeMobilePage - 1) * mobilePageSize, activeMobilePage * mobilePageSize);

  function saveRow(row: StagedTransaction, changes: StagedChanges) {
    if (!isActionableRow(row)) return;
    const normalized = changes.categoryId !== undefined && changes.subcategoryId === undefined
      ? { ...changes, subcategoryId: null }
      : changes;
    setActionError(null);
    replaceRows((current) => current.map((item) => item.id === row.id ? applyChanges(item, normalized) : item));
    queueRef.current?.enqueue(row.id, row.revision, normalized);
  }

  function retryRow(row: StagedTransaction) {
    queueRef.current?.retry(row.id, row.revision);
  }

  function cellEditRequested(event: CellEditRequestEvent<StagedTransaction>) {
    const row = event.data;
    const field = event.colDef.field;
    if (!row || !field || event.newValue === event.oldValue || !isActionableRow(row)) return;
    if (field === "categoryId") saveRow(row, { categoryId: event.newValue || null, subcategoryId: null });
    if (field === "subcategoryId") {
      saveRow(row, {
        ...(!row.categoryId && { categoryId: effectiveCategoryId(row) }),
        subcategoryId: event.newValue || null,
      });
    }
    if (field === "disposition") {
      const disposition = event.newValue as StagedTransaction["disposition"];
      const suggestion = disposition === "INCLUDE" ? suggestedLabels(row) : null;
      saveRow(row, {
        ...(suggestion ?? {}),
        disposition,
        ignoreReason: disposition === "IGNORE" ? "USER_IGNORED" : null,
      });
    }
  }

  function selectionChanged(event: SelectionChangedEvent<StagedTransaction>) {
    setSelectedIds(event.api.getSelectedRows().filter(isActionableRow).map((row) => row.id));
  }

  function bulkPatch(changes: StagedChanges) {
    for (const row of selectedVisibleRows) saveRow(row, changes);
    setSelectedIds([]);
  }

  function acceptSuggestion(row: StagedTransaction) {
    const changes = suggestionAcceptanceChanges(row);
    if (changes) saveRow(row, changes);
  }

  function acceptSelectedSuggestions() {
    for (const row of selectedSuggestedRows) acceptSuggestion(row);
    setSelectedIds([]);
  }

  function includeSelected() {
    let skipped = 0;
    for (const row of selectedVisibleRows) {
      const changes = selectedInclusionChanges(row);
      if (changes) saveRow(row, changes);
      else skipped += 1;
    }
    setSelectedIds([]);
    setActionError(
      skipped
        ? `${skipped} selected row${skipped === 1 ? " was" : "s were"} left pending because required values or categories are missing.`
        : null,
    );
  }

  async function commit() {
    setCommitting(true);
    setActionError(null);
    try {
      await api.imports.commit(id);
      navigate("/transactions");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "The import could not be committed.");
      batch.reload();
      setEditedRows(null);
      loadedRows.reload();
    } finally {
      setCommitting(false);
    }
  }

  function openDetail(row: StagedTransaction) {
    setDetailId(row.id);
    setRepair({
      date: row.date ?? "",
      description: row.description ?? "",
      amount: row.amountMinor === null ? "" : (row.amountMinor / 100).toFixed(2),
      currency: row.currency ?? "",
    });
    setRepairError(null);
  }

  function saveRepair(row: StagedTransaction) {
    if (!repair || !isActionableRow(row)) return;
    const amountMinor = parseMajorAmount(repair.amount);
    if (!isValidCalendarDate(repair.date)) {
      setRepairError("Enter a valid transaction date.");
      return;
    }
    if (!repair.description.trim()) {
      setRepairError("Description is required.");
      return;
    }
    if (amountMinor === null) {
      setRepairError("Enter an exact amount with at most two decimal places.");
      return;
    }
    if (!/^[A-Z]{3}$/.test(repair.currency.trim().toUpperCase())) {
      setRepairError("Currency must be a three-letter code.");
      return;
    }
    const signError = transactionKindError(amountMinor);
    if (signError) {
      setRepairError(signError);
      return;
    }
    setRepairError(null);
    saveRow(row, {
      transactionDate: repair.date,
      description: repair.description.trim(),
      amountMinor,
      currency: repair.currency.trim().toUpperCase(),
    });
  }

  const categoryNames = new Map(taxonomy.map((item) => [item.id, item.name]));
  const subcategoryNames = new Map(taxonomy.flatMap((item) => item.subcategories).map((item) => [item.id, item.name]));
  const columns: ColDef<StagedTransaction>[] = [
    { headerName: "", width: 48, maxWidth: 48, sortable: false, filter: false, resizable: false, cellRenderer: ({ data }: { data?: StagedTransaction }) => data ? <button className="row-action" aria-label={`Open details for row ${data.rowNumber}`} onClick={() => openDetail(data)}><Eye aria-hidden="true" /></button> : null },
    { field: "rowNumber", headerName: "Row", width: 78, cellClass: "num" },
    { field: "date", headerName: "Date", minWidth: 118, valueFormatter: ({ value }) => formatDate(value as string | null) },
    { field: "description", headerName: "Description", flex: 1, minWidth: 220, valueFormatter: ({ value }) => String(value ?? "Description unavailable") },
    { field: "amountMinor", headerName: "Amount", minWidth: 130, cellClass: "num", valueFormatter: ({ data }) => data ? formatMoney(data.amountMinor, data.currency) : "" },
    { field: "categoryId", headerName: "Category", editable: ({ data }) => Boolean(data && isActionableRow(data)), minWidth: 165, valueGetter: ({ data }) => data ? effectiveCategoryId(data) : null, valueFormatter: ({ value }) => categoryNames.get(String(value)) ?? "Uncategorized", cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["", ...taxonomy.filter((item) => item.active).map((item) => item.id)] }, cellRenderer: ({ data }: { data?: StagedTransaction }) => data ? <SuggestedValue label={categoryNames.get(String(effectiveCategoryId(data))) ?? "Uncategorized"} suggested={hasSuggestedLabels(data)} /> : null },
    { field: "subcategoryId", headerName: "Subcategory", editable: ({ data }) => Boolean(data && effectiveCategoryId(data) && isActionableRow(data)), minWidth: 170, valueGetter: ({ data }) => data ? effectiveSubcategoryId(data) : null, valueFormatter: ({ value }) => subcategoryNames.get(String(value)) ?? "None", cellEditor: "agSelectCellEditor", cellEditorParams: ({ data }: { data: StagedTransaction }) => ({ values: ["", ...subcategoriesFor(taxonomy, effectiveCategoryId(data)).map((item) => item.id)] }), cellRenderer: ({ data }: { data?: StagedTransaction }) => data ? <SuggestedValue label={subcategoryNames.get(String(effectiveSubcategoryId(data))) ?? "None"} suggested={hasSuggestedLabels(data) && Boolean(effectiveSubcategoryId(data))} /> : null },
    { field: "confidence", headerName: "Confidence", minWidth: 130, cellRenderer: ({ data, value }: { data?: StagedTransaction; value: number | null }) => value === null ? <StatusBadge>Manual</StatusBadge> : <StatusBadge tone={hasSuggestedLabels(data!) ? "warn" : value >= .8 ? "good" : value >= .55 ? "warn" : "bad"}>{Math.round(value * 100)}%{hasSuggestedLabels(data!) ? " suggested" : ""}</StatusBadge> },
    { field: "duplicateState", headerName: "Duplicate", minWidth: 125, cellRenderer: ({ value }: { value: StagedTransaction["duplicateState"] }) => <StatusBadge tone={value === "EXACT" ? "bad" : value === "LIKELY" ? "warn" : "neutral"}>{value}</StatusBadge> },
    { field: "disposition", headerName: "Disposition", editable: ({ data }) => Boolean(data && isActionableRow(data)), minWidth: 125, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["INCLUDE", "IGNORE"] }, cellRenderer: ({ value }: { value: StagedTransaction["disposition"] }) => <StatusBadge tone={value === "INCLUDE" || value === "COMMITTED" ? "good" : value === "BLOCKED" ? "bad" : "warn"}>{value}</StatusBadge> },
    { headerName: "Save", minWidth: 115, sortable: false, filter: false, cellRenderer: ({ data }: { data?: StagedTransaction }) => {
      if (!data || !isActionableRow(data)) return null;
      const state = saveStates[data.id] ?? "IDLE";
      if (state === "CONFLICT" || state === "ERROR") return <button className="button ghost" onClick={() => retryRow(data)}><RotateCcw aria-hidden="true" /> {state === "CONFLICT" ? "Conflict" : "Retry"}</button>;
      return <span className={`save-status ${state.toLowerCase()}`}>{state === "SAVING" ? "Saving..." : state === "SAVED" ? "Saved" : ""}</span>;
    } },
  ];

  if (batch.loading || loadedRows.loading || categories.loading) return <><PageHeader title="Import review" description="Loading staged rows and taxonomy." /><LoadingState label="Preparing bounded review rows" /></>;
  if (batch.error) return <><PageHeader title="Import review" description="The import batch could not be opened." /><ErrorState error={batch.error} retry={batch.reload} /></>;
  if (loadedRows.error) return <><PageHeader title="Import review" description="The staged rows could not be opened." /><ErrorState error={loadedRows.error} retry={loadedRows.reload} /></>;
  if (categories.error) return <><PageHeader title="Import review" description="The taxonomy could not be loaded." /><ErrorState error={categories.error} retry={categories.reload} /></>;

  return (
    <>
      <PageHeader
        eyebrow={`Import / ${batch.data?.status.replaceAll("_", " ") ?? "Draft"}`}
        title={batch.data?.filename ?? "Import review"}
        description="Review staged rows with serialized autosaves. Historical and blocked rows remain view-only under the explicit All filter."
        actions={<><Link className="button secondary" to="/import">Back to imports</Link>{batch.data && draftStatuses.has(batch.data.status) && <button className="button" disabled={committing || invalid > 0 || pendingRows > 0 || unsafeSaveState} onClick={commit}>{committing ? "Committing..." : "Commit accepted rows"}</button>}</>}
      />

      <ol className="workflow" aria-label="Import workflow">
        <li className="workflow-step complete" data-step="1"><strong>Source / File</strong><span>Original retained</span></li>
        <li className="workflow-step complete" data-step="2"><strong>Parse Summary</strong><span>{rows.length} bounded rows</span></li>
        <li className="workflow-step active" data-step="3" aria-current="step"><strong>Review</strong><span>{unresolved} actionable signals</span></li>
        <li className="workflow-step" data-step="4"><strong>Commit</strong><span>Atomic ledger write</span></li>
      </ol>

      <div className="review-summary" aria-live="polite">
        <StatusBadge tone={unresolved ? "warn" : "good"}>{unresolved} need attention</StatusBadge>
        <StatusBadge tone={invalid ? "bad" : "good"}>{invalid} actionable invalid</StatusBadge>
        <StatusBadge>{rows.filter((row) => isActionableRow(row) && row.duplicateState === "LIKELY").length} likely duplicates</StatusBadge>
        <StatusBadge tone={blocked ? "bad" : "neutral"}>{blocked} blocked exact duplicates</StatusBadge>
        <StatusBadge tone={rows.some(hasSuggestedLabels) ? "warn" : "neutral"}>{rows.filter(hasSuggestedLabels).length} suggested labels</StatusBadge>
        <StatusBadge>{rows.filter((row) => row.disposition === "IGNORE").length} ignored</StatusBadge>
      </div>
      {actionError && <InlineNotice tone="bad">{actionError}</InlineNotice>}

      <div className="grid-toolbar">
        <div className="grid-toolbar-group" role="group" aria-label="Review row filters">
          <Field label="Search description" htmlFor="review-description-search"><input id="review-description-search" className="search-field" type="search" placeholder="Merchant or description" value={descriptionSearch} onChange={(event) => { setDescriptionSearch(event.target.value); setSelectedIds([]); setMobilePage(1); }} /></Field>
          {descriptionSearch && <button type="button" className="button ghost" onClick={() => { setDescriptionSearch(""); setSelectedIds([]); setMobilePage(1); }}>Clear search</button>}
          {filters.map((item) => <button key={item.value} className={activeFilter === item.value ? "button" : "button secondary"} aria-pressed={activeFilter === item.value} onClick={() => { setFilter(item.value); setSelectedIds([]); setMobilePage(1); }}>{item.label}</button>)}
        </div>
        <div className="grid-toolbar-group">
          <Field label="Bulk category" htmlFor="bulk-review-category"><select id="bulk-review-category" value={bulkCategoryId} onChange={(event) => setBulkCategoryId(event.target.value)}><option value="">Choose category</option>{taxonomy.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
          <button className="button secondary" disabled={!selectedVisibleRows.length || !bulkCategoryId} onClick={() => bulkPatch({ categoryId: bulkCategoryId, subcategoryId: null })}>Apply category</button>
          <button className="button secondary" disabled={!selectedSuggestedRows.length} onClick={acceptSelectedSuggestions}>Accept suggested labels</button>
          <button className="button secondary" disabled={!selectedVisibleRows.length || unsafeSaveState} onClick={includeSelected}>Include selected</button>
          <button className="button secondary" disabled={!selectedVisibleRows.length} onClick={() => bulkPatch({ disposition: "IGNORE", ignoreReason: "USER_IGNORED" })}>Ignore selected</button>
        </div>
      </div>
      <p className="notice" aria-live="polite">Bulk actions apply only to {selectedVisibleRows.length} selected visible actionable {selectedVisibleRows.length === 1 ? "row" : "rows"}.</p>

      {visibleRows.length ? !isMobile ? (
        <div className="grid-frame">
          <AgGridReact<StagedTransaction>
            theme={ledgerGridTheme}
            rowData={visibleRows}
            columnDefs={columns}
            getRowId={({ data }) => data.id}
            rowSelection={{
              mode: "multiRow",
              isRowSelectable: ({ data }) => Boolean(data && isActionableRow(data)),
            }}
            onSelectionChanged={selectionChanged}
            onCellEditRequest={cellEditRequested}
            readOnlyEdit
            stopEditingWhenCellsLoseFocus
            singleClickEdit
            animateRows={false}
          />
        </div>
      ) : (
        <div className="mobile-records mounted">
          {mobileRows.map((row) => (
            <article className="record-card" key={row.id}>
              <div className="record-card-header"><div>{isActionableRow(row) && <label className="checkbox-field"><input type="checkbox" checked={selectedIds.includes(row.id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...new Set([...current, row.id])] : current.filter((item) => item !== row.id))} /> Select row {row.rowNumber}</label>}<h3>{row.description ?? "Description unavailable"}</h3><p>{formatDate(row.date)} / row {row.rowNumber}</p></div><strong className="amount">{formatMoney(row.amountMinor, row.currency)}</strong></div>
              {isActionableRow(row) ? <div className="form-grid">
                <Field label={hasSuggestedLabels(row) ? "Category (suggested)" : "Category"} htmlFor={`mobile-category-${row.id}`}><select id={`mobile-category-${row.id}`} value={effectiveCategoryId(row) ?? ""} onChange={(event) => saveRow(row, { categoryId: event.target.value || null, subcategoryId: null })}><option value="">Uncategorized</option>{taxonomy.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
                <Field label={hasSuggestedLabels(row) && effectiveSubcategoryId(row) ? "Subcategory (suggested)" : "Subcategory"} htmlFor={`mobile-subcategory-${row.id}`}><select id={`mobile-subcategory-${row.id}`} disabled={!effectiveCategoryId(row)} value={effectiveSubcategoryId(row) ?? ""} onChange={(event) => saveRow(row, { ...(!row.categoryId && { categoryId: effectiveCategoryId(row) }), subcategoryId: event.target.value || null })}><option value="">None</option>{subcategoriesFor(taxonomy, effectiveCategoryId(row)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
                <Field label="Disposition" htmlFor={`mobile-disposition-${row.id}`}><select id={`mobile-disposition-${row.id}`} value={row.disposition} onChange={(event) => { const disposition = event.target.value as StagedTransaction["disposition"]; const suggestion = disposition === "INCLUDE" ? suggestedLabels(row) : null; saveRow(row, { ...(suggestion ?? {}), disposition, ignoreReason: disposition === "IGNORE" ? "USER_IGNORED" : null }); }}><option>INCLUDE</option><option>IGNORE</option></select></Field>
                {hasSuggestedLabels(row) && <button className="button secondary" onClick={() => acceptSuggestion(row)}>Accept suggestion</button>}
              </div> : <InlineNotice>Historical and blocked rows are view-only.</InlineNotice>}
              <div className="record-card-footer"><span><StatusBadge tone={row.duplicateState === "EXACT" ? "bad" : row.duplicateState === "LIKELY" ? "warn" : "neutral"}>{row.duplicateState} duplicate</StatusBadge></span><button className="button ghost" onClick={() => openDetail(row)}>{row.errors.length && isActionableRow(row) ? "Repair or inspect" : "Open details"}</button></div>
            </article>
          ))}
          {mobilePageCount > 1 && <div className="pagination"><button className="button secondary" disabled={activeMobilePage <= 1} onClick={() => setMobilePage((value) => value - 1)}>Previous</button><span>Page {activeMobilePage} of {mobilePageCount}</span><button className="button secondary" disabled={activeMobilePage >= mobilePageCount} onClick={() => setMobilePage((value) => value + 1)}>Next</button></div>}
        </div>
      ) : <EmptyState title="No matching rows" description={descriptionSearch ? "Clear or change the description search, or choose another review filter." : "Choose a different review filter. Historical rows are available only under All."} />}

      <Drawer
        open={Boolean(detail)}
        title={detail?.description ?? "Staged row"}
        description={detail ? `Row ${detail.rowNumber} / revision ${detail.revision}` : undefined}
        onClose={() => setDetailId(null)}
        footer={detail && isActionableRow(detail) && (saveStates[detail.id] === "CONFLICT" || saveStates[detail.id] === "ERROR") ? <button className="button secondary" onClick={() => retryRow(detail)}><RotateCcw aria-hidden="true" /> Retry row save</button> : undefined}
      >
        {detail && (
          <>
            <section className="detail-section"><h3>Normalized transaction</h3><dl className="detail-list"><dt>Date</dt><dd>{formatDate(detail.date)}</dd><dt>Amount</dt><dd className="num">{formatMoney(detail.amountMinor, detail.currency)}</dd><dt>Category</dt><dd><SuggestedValue label={categoryName(taxonomy, effectiveCategoryId(detail))} suggested={hasSuggestedLabels(detail)} /></dd><dt>Subcategory</dt><dd><SuggestedValue label={subcategoryName(taxonomy, effectiveSubcategoryId(detail))} suggested={hasSuggestedLabels(detail) && Boolean(effectiveSubcategoryId(detail))} /></dd><dt>Disposition</dt><dd>{detail.disposition}</dd></dl></section>
            {detail.errors.length > 0 && isActionableRow(detail) && repair && <section className="detail-section"><h3>Repair invalid row</h3><div className="form-grid">
              <Field label="Date" htmlFor="repair-date"><input id="repair-date" type="date" value={repair.date} onChange={(event) => setRepair({ ...repair, date: event.target.value })} /></Field>
              <Field label="Description" htmlFor="repair-description"><input id="repair-description" value={repair.description} onChange={(event) => setRepair({ ...repair, description: event.target.value })} /></Field>
              <Field label="Amount" htmlFor="repair-amount" hint="Signed amount with at most two decimal places"><input id="repair-amount" inputMode="decimal" value={repair.amount} onChange={(event) => setRepair({ ...repair, amount: event.target.value })} /></Field>
              <Field label="Currency" htmlFor="repair-currency"><input id="repair-currency" maxLength={3} value={repair.currency} onChange={(event) => setRepair({ ...repair, currency: event.target.value.toUpperCase() })} /></Field>
            </div>{repairError && <InlineNotice tone="bad">{repairError}</InlineNotice>}<div className="form-actions"><button className="button" onClick={() => saveRepair(detail)}>Save repaired values</button><button className="button secondary" onClick={() => saveRow(detail, { disposition: "IGNORE", ignoreReason: "USER_IGNORED" })}>Ignore row instead</button></div></section>}
            <section className="detail-section"><h3>Prediction</h3><dl className="detail-list"><dt>Category</dt><dd>{categoryName(taxonomy, detail.predictedCategoryId)}</dd><dt>Subcategory</dt><dd>{subcategoryName(taxonomy, detail.predictedSubcategoryId)}</dd><dt>Confidence</dt><dd>{detail.confidence === null ? "No model prediction" : `${Math.round(detail.confidence * 100)}%`}</dd></dl>{hasSuggestedLabels(detail) && <button className="button secondary" onClick={() => acceptSuggestion(detail)}>Accept suggestion</button>}{isActionableRow(detail) && <label className="checkbox-field"><input type="checkbox" checked={detail.rememberCorrection} onChange={(event) => saveRow(detail, { rememberCorrection: event.target.checked })} /> Remember this correction as an exact-match rule</label>}</section>
            <section className="detail-section"><h3>Duplicate review</h3>{detail.duplicateState === "NONE" ? <p>No duplicate candidate was found.</p> : <><InlineNotice tone={detail.duplicateState === "EXACT" ? "bad" : "warn"}><AlertTriangle aria-hidden="true" /> {detail.duplicateExplanation ?? `${detail.duplicateState} duplicate signal`}</InlineNotice>{detail.duplicateCandidate && <pre className="raw-data">{JSON.stringify(detail.duplicateCandidate, null, 2)}</pre>}</>}</section>
            <section className="detail-section"><h3>Validation</h3>{detail.errors.length ? detail.errors.map((error) => <InlineNotice tone="bad" key={error}>{error}</InlineNotice>) : <InlineNotice tone="good"><Check aria-hidden="true" /> No validation errors</InlineNotice>}</section>
            <section className="detail-section"><h3>Normalized data</h3><pre className="raw-data">{JSON.stringify(detail.normalized, null, 2)}</pre></section>
            <section className="detail-section"><h3>Raw source row</h3><pre className="raw-data">{JSON.stringify(detail.raw, null, 2)}</pre></section>
          </>
        )}
      </Drawer>
    </>
  );
}
