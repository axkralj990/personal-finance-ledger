import { useState, type FormEvent } from "react";
import type { CellValueChangedEvent, ColDef, SelectionChangedEvent } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { Minus, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import type { ManualTransactionInput } from "../api/types";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader } from "../components/ui";
import { manualRowError, toManualInput, type ManualRow } from "../features/manual-input";
import { useResource } from "../hooks/use-resource";
import { useMediaQuery } from "../hooks/use-media-query";
import { localCalendarDate } from "../shared/format";
import { ledgerGridTheme } from "../shared/grid-theme";
import { subcategoriesFor, taxonomyError } from "../shared/taxonomy";

const createId = () => globalThis.crypto?.randomUUID?.() ?? `manual-${Date.now()}-${Math.random()}`;
const newRow = (): ManualRow => ({ id: createId(), sourceAccountId: "", date: localCalendarDate(), description: "", amount: "", currency: "", categoryId: "", subcategoryId: "" });

export default function ManualEntryPage() {
  const navigate = useNavigate();
  const accounts = useResource(() => api.sourceAccounts.list(), "manual-accounts");
  const categories = useResource(() => api.taxonomy.categories(), "manual-categories");
  const [tab, setTab] = useState<"quick" | "bulk">("quick");
  const [quick, setQuick] = useState(newRow);
  const [rows, setRows] = useState<ManualRow[]>(() => [newRow(), newRow(), newRow()]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<{ id: string; description: string } | null>(null);
  const [mobilePage, setMobilePage] = useState(1);
  const isMobile = useMediaQuery("(max-width: 700px)");
  const taxonomy = categories.data ?? [];
  const activeAccounts = accounts.data?.filter((item) => item.active) ?? [];
  const manualAccount = activeAccounts.find((item) => item.provider.toUpperCase() === "MANUAL");
  const withAccountDefault = (row: ManualRow): ManualRow => row.sourceAccountId || !manualAccount
    ? row
    : { ...row, sourceAccountId: manualAccount.id, currency: row.currency || manualAccount.defaultCurrency };
  const quickWithDefault = withAccountDefault(quick);
  const rowsWithDefaults = rows.map(withAccountDefault);
  const quickTaxonomyError = taxonomyError(taxonomy, quick.categoryId || null, quick.subcategoryId || null);
  const mobilePageCount = Math.max(1, Math.ceil(rowsWithDefaults.length / 10));
  const activeMobilePage = Math.min(mobilePage, mobilePageCount);

  function updateQuick<K extends keyof ManualRow>(key: K, value: ManualRow[K]) {
    setQuick((current) => ({ ...current, [key]: value }));
  }

  async function saveQuick(addAnother: boolean) {
    const input = toManualInput(quickWithDefault);
    if (!input || quickTaxonomyError) {
      setError(quickTaxonomyError ?? manualRowError(quickWithDefault));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const batch = await api.manualImports.create([input]);
      if (addAnother) {
        setSavedDraft({ id: batch.id, description: quick.description });
        setQuick({ ...newRow(), sourceAccountId: quickWithDefault.sourceAccountId, currency: quickWithDefault.currency });
      } else {
        navigate(`/imports/${batch.id}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The manual draft could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitBulk(event: FormEvent) {
    event.preventDefault();
    const populated = rowsWithDefaults.filter((row) => row.description.trim() || row.amount.trim());
    const inputs = populated.map(toManualInput);
    const invalidRow = populated.find((row) => manualRowError(row));
    const invalidTaxonomy = populated.find((row) => taxonomyError(taxonomy, row.categoryId || null, row.subcategoryId || null));
    const accountIds = new Set(populated.map((row) => row.sourceAccountId));
    if (!populated.length || inputs.some((item) => !item) || invalidTaxonomy || accountIds.size !== 1) {
      setError(invalidTaxonomy
        ? "One row has a subcategory outside its selected parent category."
        : accountIds.size > 1
          ? "A bulk manual draft can contain rows from one account only."
          : invalidRow ? manualRowError(invalidRow) : "Complete every populated bulk row before creating the review draft.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const batch = await api.manualImports.create(inputs as ManualTransactionInput[]);
      navigate(`/imports/${batch.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The bulk draft could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  const categoryNames = new Map(taxonomy.map((item) => [item.id, item.name]));
  const subcategoryNames = new Map(taxonomy.flatMap((item) => item.subcategories).map((item) => [item.id, item.name]));
  const columns: ColDef<ManualRow>[] = [
    { field: "date", headerName: "Date", editable: true, minWidth: 130 },
    { field: "description", headerName: "Description", editable: true, flex: 1, minWidth: 210 },
    { field: "amount", headerName: "Amount", editable: true, width: 120, cellClass: "num" },
    { field: "currency", headerName: "Currency", editable: true, width: 105 },
    { field: "sourceAccountId", headerName: "Account", editable: true, cellEditor: "agSelectCellEditor", cellEditorParams: { values: activeAccounts.map((item) => item.id) }, valueFormatter: ({ value }) => activeAccounts.find((item) => item.id === value)?.displayName ?? "Choose", minWidth: 150 },
    { field: "categoryId", headerName: "Category", editable: true, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["", ...taxonomy.filter((item) => item.active).map((item) => item.id)] }, valueFormatter: ({ value }) => categoryNames.get(String(value)) ?? "None", minWidth: 135 },
    { field: "subcategoryId", headerName: "Subcategory", editable: ({ data }) => Boolean(data?.categoryId), cellEditor: "agSelectCellEditor", cellEditorParams: ({ data }: { data: ManualRow }) => ({ values: ["", ...subcategoriesFor(taxonomy, data.categoryId || null).map((item) => item.id)] }), valueFormatter: ({ value }) => subcategoryNames.get(String(value)) ?? "None", minWidth: 145 },
  ];

  function cellChanged(event: CellValueChangedEvent<ManualRow>) {
    if (!event.data) return;
    const updated = { ...event.data };
    if (event.colDef.field === "categoryId") updated.subcategoryId = "";
    if (event.colDef.field === "sourceAccountId" && !updated.currency) {
      updated.currency = activeAccounts.find((item) => item.id === updated.sourceAccountId)?.defaultCurrency ?? "";
    }
    setRows((current) => current.map((row) => row.id === updated.id ? updated : row));
  }

  function selectionChanged(event: SelectionChangedEvent<ManualRow>) {
    setSelectedIds(event.api.getSelectedRows().map((row) => row.id));
  }

  function updateMobileRow(id: string, patch: Partial<ManualRow>) {
    setRows((current) => current.map((row) => row.id === id ? { ...row, ...patch } : row));
  }

  if (accounts.loading || categories.loading) return <><PageHeader title="Manual entry" description="Prepare ledger rows without a statement file." /><LoadingState /></>;
  if (accounts.error) return <><PageHeader title="Manual entry" description="Prepare ledger rows without a statement file." /><ErrorState error={accounts.error} retry={accounts.reload} /></>;
  if (categories.error) return <><PageHeader title="Manual entry" description="Prepare ledger rows without a statement file." /><ErrorState error={categories.error} retry={categories.reload} /></>;

  return (
    <>
      <PageHeader eyebrow="Manual ingestion" title="Manual entry" description="Quick entry saves one reviewable draft at a time. Bulk entry creates one bounded draft with keyboard-editable cells, without spreadsheet range-paste behavior." />
      <div className="tabs" aria-label="Manual entry mode">
        <button className="tab-button" aria-pressed={tab === "quick"} onClick={() => setTab("quick")}>Quick</button>
        <button className="tab-button" aria-pressed={tab === "bulk"} onClick={() => setTab("bulk")}>Bulk</button>
      </div>
      {error && <InlineNotice tone="bad">{error}</InlineNotice>}
      {savedDraft && <InlineNotice tone="good">Saved "{savedDraft.description}" as a review draft. <Link to={`/imports/${savedDraft.id}`}>Review that draft</Link>, or add another below.</InlineNotice>}

      {tab === "quick" ? (
        <section id="quick-panel" className="ledger-panel panel-padding">
          <div className="section-heading"><h2>One transaction</h2><p>Saved through manual import review</p></div>
          <div className="form-grid">
            <Field label="Account" htmlFor="quick-account"><select id="quick-account" value={quickWithDefault.sourceAccountId} onChange={(event) => { const account = activeAccounts.find((item) => item.id === event.target.value); setQuick((current) => ({ ...current, sourceAccountId: event.target.value, currency: current.currency || account?.defaultCurrency || "" })); }}><option value="">Choose account</option>{activeAccounts.map((item) => <option key={item.id} value={item.id}>{item.displayName}</option>)}</select></Field>
            <Field label="Date" htmlFor="quick-date"><input id="quick-date" type="date" value={quick.date} onChange={(event) => updateQuick("date", event.target.value)} /></Field>
            <Field label="Description" htmlFor="quick-description"><input id="quick-description" value={quick.description} onChange={(event) => updateQuick("description", event.target.value)} placeholder="Merchant or note" /></Field>
            <Field label="Amount" htmlFor="quick-amount" hint="Enter the signed major-unit amount"><input id="quick-amount" inputMode="decimal" value={quick.amount} onChange={(event) => updateQuick("amount", event.target.value)} placeholder="-24.90" /></Field>
            <Field label="Currency" htmlFor="quick-currency"><input id="quick-currency" maxLength={3} value={quickWithDefault.currency} onChange={(event) => updateQuick("currency", event.target.value.toUpperCase())} placeholder="SGD" /></Field>
            <Field label="Category" htmlFor="quick-category"><select id="quick-category" value={quick.categoryId} onChange={(event) => setQuick((current) => ({ ...current, categoryId: event.target.value, subcategoryId: "" }))}><option value="">Uncategorized</option>{taxonomy.filter((item) => item.active).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></Field>
             <Field label="Subcategory" htmlFor="quick-subcategory" error={quickTaxonomyError}>{(accessibility) => <select {...accessibility} id="quick-subcategory" disabled={!quick.categoryId} value={quick.subcategoryId} onChange={(event) => updateQuick("subcategoryId", event.target.value)}><option value="">None</option>{subcategoriesFor(taxonomy, quick.categoryId || null).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>}</Field>
          </div>
          <div className="form-actions"><button className="button" disabled={submitting} onClick={() => saveQuick(false)}>{submitting ? "Saving..." : "Save for review"}</button><button className="button secondary" disabled={submitting} onClick={() => saveQuick(true)}>Save and add another</button></div>
        </section>
      ) : (
        <form id="bulk-panel" onSubmit={submitBulk}>
          <div className="grid-toolbar"><div><h2>Bulk draft</h2><p className="page-intro">Use Tab, Enter, and arrow keys to edit. Actions operate on selected rows, not cell ranges.</p></div><div className="grid-toolbar-group"><button type="button" className="button secondary" onClick={() => setRows((current) => [...current, newRow()])}><Plus aria-hidden="true" /> Add row</button><button type="button" className="button danger" disabled={!selectedIds.length} onClick={() => { setRows((current) => current.filter((row) => !selectedIds.includes(row.id))); setSelectedIds([]); }}><Minus aria-hidden="true" /> Remove selected</button></div></div>
           {!isMobile ? <div className="grid-frame compact">
             <AgGridReact<ManualRow> theme={ledgerGridTheme} rowData={rowsWithDefaults} columnDefs={columns} getRowId={({ data }) => data.id} rowSelection={{ mode: "multiRow" }} onCellValueChanged={cellChanged} onSelectionChanged={selectionChanged} stopEditingWhenCellsLoseFocus singleClickEdit />
           </div> : <div className="mobile-records mounted">
             {rowsWithDefaults.slice((activeMobilePage - 1) * 10, activeMobilePage * 10).map((row, pageIndex) => (
               <article className="record-card" key={row.id}>
                 <h3>Row {(activeMobilePage - 1) * 10 + pageIndex + 1}</h3>
                 <div className="form-grid">
                   <Field label="Account" htmlFor={`mobile-account-${row.id}`}><select id={`mobile-account-${row.id}`} value={row.sourceAccountId} onChange={(event) => { const account = activeAccounts.find((item) => item.id === event.target.value); updateMobileRow(row.id, { sourceAccountId: event.target.value, currency: row.currency || account?.defaultCurrency || "" }); }}><option value="">Choose account</option>{activeAccounts.map((item) => <option key={item.id} value={item.id}>{item.displayName}</option>)}</select></Field>
                   <Field label="Description" htmlFor={`mobile-desc-${row.id}`}><input id={`mobile-desc-${row.id}`} value={row.description} onChange={(event) => updateMobileRow(row.id, { description: event.target.value })} /></Field>
                   <Field label="Amount" htmlFor={`mobile-amount-${row.id}`}><input id={`mobile-amount-${row.id}`} inputMode="decimal" value={row.amount} onChange={(event) => updateMobileRow(row.id, { amount: event.target.value })} /></Field>
                   <Field label="Date" htmlFor={`mobile-date-${row.id}`}><input id={`mobile-date-${row.id}`} type="date" value={row.date} onChange={(event) => updateMobileRow(row.id, { date: event.target.value })} /></Field>
                   <Field label="Currency" htmlFor={`mobile-currency-${row.id}`}><input id={`mobile-currency-${row.id}`} maxLength={3} value={row.currency} onChange={(event) => updateMobileRow(row.id, { currency: event.target.value.toUpperCase() })} /></Field>
                   <Field label="Category" htmlFor={`mobile-category-${row.id}`}><select id={`mobile-category-${row.id}`} value={row.categoryId} onChange={(event) => updateMobileRow(row.id, { categoryId: event.target.value, subcategoryId: "" })}><option value="">Uncategorized</option>{taxonomy.filter((item) => item.active).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></Field>
                   <Field label="Subcategory" htmlFor={`mobile-subcategory-${row.id}`} error={taxonomyError(taxonomy, row.categoryId || null, row.subcategoryId || null)}>{(accessibility) => <select {...accessibility} id={`mobile-subcategory-${row.id}`} disabled={!row.categoryId} value={row.subcategoryId} onChange={(event) => updateMobileRow(row.id, { subcategoryId: event.target.value })}><option value="">None</option>{subcategoriesFor(taxonomy, row.categoryId || null).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>}</Field>
                 </div>
                 <button type="button" className="button danger" onClick={() => setRows((current) => current.filter((item) => item.id !== row.id))}>Remove row</button>
               </article>
             ))}
             {rowsWithDefaults.length > 10 && <div className="pagination"><button type="button" className="button secondary" disabled={activeMobilePage <= 1} onClick={() => setMobilePage((value) => value - 1)}>Previous</button><span>Page {activeMobilePage} of {mobilePageCount}</span><button type="button" className="button secondary" disabled={activeMobilePage >= mobilePageCount} onClick={() => setMobilePage((value) => value + 1)}>Next</button></div>}
           </div>}
          {!rows.length && <EmptyState title="No bulk rows" description="Add a row to begin the manual import draft." />}
          <div className="form-actions"><button className="button" disabled={submitting || !rows.length}>{submitting ? "Creating draft..." : "Create review draft"}</button></div>
        </form>
      )}
    </>
  );
}
