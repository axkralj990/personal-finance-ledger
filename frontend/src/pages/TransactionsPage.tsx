import { useEffect, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { ApiProblem, api } from "../api/client";
import type { Transaction } from "../api/types";
import { Drawer } from "../components/Drawer";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader } from "../components/ui";
import { useResource } from "../hooks/use-resource";
import { formatDate, formatMoney, minorToMajorInput, parseMajorAmount } from "../shared/format";
import { subcategoriesFor, taxonomyError } from "../shared/taxonomy";

export default function TransactionsPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ currency: "", dateFrom: "", dateTo: "", accountId: "", categoryId: "", search: "" });
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [edit, setEdit] = useState({ amount: "", categoryId: "", subcategoryId: "" });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const accounts = useResource(() => api.accounts.list(), "transaction-accounts");
  const categories = useResource(() => api.taxonomy.categories(), "transaction-categories");
  const currencies = useResource(() => api.transactions.currencies(), "transaction-currencies");
  const queryKey = JSON.stringify({ ...filters, page });
  const transactions = useResource(
    () => api.transactions.list({ ...filters, page, pageSize: 25 }),
    queryKey,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setFilters((current) => ({ ...current, search }));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  function openTransaction(transaction: Transaction) {
    setSelected(transaction);
    setEdit({ amount: minorToMajorInput(transaction.amountMinor), categoryId: transaction.categoryId ?? "", subcategoryId: transaction.subcategoryId ?? "" });
    setSaveError(null);
  }

  const setFilter = <K extends keyof typeof filters>(name: K, value: (typeof filters)[K]) => {
    setPage(1);
    setFilters((current) => ({ ...current, [name]: value }));
  };
  const subcategories = subcategoriesFor(categories.data ?? [], edit.categoryId || null);
  const combinationError = taxonomyError(categories.data ?? [], edit.categoryId || null, edit.subcategoryId || null);
  const parsedAmount = parseMajorAmount(edit.amount);
  const amountError = parsedAmount === null
    ? "Enter a signed amount with at most two decimal places."
    : parsedAmount === 0
      ? "Amount cannot be zero."
      : null;

  async function saveCorrection() {
    if (!selected || combinationError || amountError || parsedAmount === null) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.transactions.patch(selected.id, {
        expectedRevision: selected.revision,
        amountMinor: parsedAmount,
        categoryId: edit.categoryId || null,
        subcategoryId: edit.subcategoryId || null,
      });
      setSelected(updated);
      transactions.reload();
    } catch (error) {
      if (error instanceof ApiProblem && error.status === 409) {
        try {
          const currentPage = await api.transactions.list({ ...filters, page, pageSize: 25 });
          const current = currentPage.items.find((item) => item.id === selected.id);
          if (current) openTransaction(current);
          setSaveError("This transaction changed elsewhere. Current values were reloaded; review and save again.");
          transactions.reload();
        } catch (reloadError) {
          setSaveError(reloadError instanceof Error ? reloadError.message : "The current transaction could not be reloaded.");
        }
      } else {
        setSaveError(error instanceof Error ? error.message : "Changes could not be saved.");
      }
    } finally {
      setSaving(false);
    }
  }

  async function deleteTransaction() {
    if (!selected) return;
    const confirmed = window.confirm(
      `Permanently delete ${selected.description} from ${formatDate(selected.date)} for ${formatMoney(selected.amountMinor, selected.currency)}? This cannot be undone.`,
    );
    if (!confirmed) return;
    setDeleting(true);
    setSaveError(null);
    try {
      await api.transactions.delete(selected.id, selected.revision);
      setSelected(null);
      transactions.reload();
      currencies.reload();
    } catch (error) {
      if (error instanceof ApiProblem && error.status === 409) {
        setSaveError("This transaction changed elsewhere. Reload the page and review it before deleting.");
        transactions.reload();
      } else {
        setSaveError(error instanceof Error ? error.message : "The transaction could not be deleted.");
      }
    } finally {
      setDeleting(false);
    }
  }

  const data = transactions.data;
  const hasFilters = Object.values(filters).some(Boolean);
  const fallbackCurrencies = [...new Set(accounts.data?.map((account) => account.defaultCurrency).filter(Boolean) ?? [])];
  const currencyOptions = currencies.data?.length ? currencies.data : fallbackCurrencies;
  return (
    <>
      <PageHeader eyebrow="Committed ledger" title="Transactions" description="Search and correct the durable ledger. Every correction uses a stable row identity and revision; exclusions remain auditable." />
      <div className="filter-bar" aria-label="Transaction filters">
        <Field label="Search description" htmlFor="transaction-search"><input id="transaction-search" className="search-field" type="search" placeholder="Merchant or description" value={search} onChange={(event) => setSearch(event.target.value)} /></Field>
        {search && <button type="button" className="button ghost" onClick={() => setSearch("")}>Clear search</button>}
        <Field label="Currency" htmlFor="transaction-currency"><select id="transaction-currency" value={filters.currency} onChange={(event) => setFilter("currency", event.target.value)}><option value="">All currencies</option>{currencyOptions.map((currency) => <option key={currency}>{currency}</option>)}</select></Field>
        <Field label="Account" htmlFor="transaction-account"><select id="transaction-account" value={filters.accountId} onChange={(event) => setFilter("accountId", event.target.value)}><option value="">All accounts</option>{accounts.data?.map((account) => <option value={account.id} key={account.id}>{account.name}</option>)}</select></Field>
        <Field label="Category" htmlFor="transaction-category"><select id="transaction-category" value={filters.categoryId} onChange={(event) => setFilter("categoryId", event.target.value)}><option value="">All categories</option>{categories.data?.map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}</select></Field>
        <Field label="From" htmlFor="transaction-from"><input id="transaction-from" type="date" value={filters.dateFrom} onChange={(event) => setFilter("dateFrom", event.target.value)} /></Field>
        <Field label="To" htmlFor="transaction-to"><input id="transaction-to" type="date" value={filters.dateTo} onChange={(event) => setFilter("dateTo", event.target.value)} /></Field>
      </div>

      {accounts.error && <ErrorState error={accounts.error} retry={accounts.reload} />}
      {categories.error && <ErrorState error={categories.error} retry={categories.reload} />}
      {(accounts.loading || categories.loading) && <InlineNotice>Loading account and taxonomy filters.</InlineNotice>}
      {currencies.error && <InlineNotice tone="warn">Currency discovery is unavailable. Showing account default currencies.</InlineNotice>}

      {transactions.loading ? <LoadingState label="Reading transaction pages" /> :
        transactions.error ? <ErrorState error={transactions.error} retry={transactions.reload} /> :
        !data?.items.length ? <EmptyState title={hasFilters ? "No matching transactions" : "The ledger is empty"} description={hasFilters ? "Change or clear filters to widen the server query." : "Commit an import or manual entry to begin the ledger."} /> : (
          <>
            <div className="desktop-table">
              <table className="data-table">
                <thead><tr><th>Date</th><th>Description</th><th>Account</th><th>Category</th><th className="amount">Amount</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDate(item.date)}</td>
                    <td><strong>{item.description}</strong></td>
                    <td>{item.accountName}</td>
                    <td>{item.categoryName ?? "Uncategorized"}{item.subcategoryName && <><br /><small>{item.subcategoryName}</small></>}</td>
                    <td className="amount">{formatMoney(item.amountMinor, item.currency)}</td>
                    <td><button className="row-action" aria-label={`Edit ${item.description}`} onClick={() => openTransaction(item)}><MoreHorizontal aria-hidden="true" /></button></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div className="mobile-records">
              {data.items.map((item) => (
                <article className="record-card" key={item.id}>
                  <div className="record-card-header"><div><h3>{item.description}</h3><p>{formatDate(item.date)} / {item.accountName}</p></div><strong className="amount">{formatMoney(item.amountMinor, item.currency)}</strong></div>
                  <div className="record-card-footer"><span>{item.categoryName ?? "Uncategorized"}</span><button className="button ghost" onClick={() => openTransaction(item)}>Correct</button></div>
                </article>
              ))}
            </div>
            <div className="pagination">
              <button className="button secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button>
              <span className="num">Page {data.page} / {data.total} records</span>
              <button className="button secondary" disabled={page * data.pageSize >= data.total} onClick={() => setPage((value) => value + 1)}>Next</button>
            </div>
          </>
        )}

      <Drawer open={Boolean(selected)} title={selected?.description ?? "Transaction"} description={selected ? `${formatDate(selected.date)} / revision ${selected.revision}` : undefined} onClose={() => setSelected(null)} footer={<><button className="button danger" disabled={saving || deleting} onClick={deleteTransaction}>{deleting ? "Deleting..." : "Delete permanently"}</button><button className="button" disabled={saving || deleting || Boolean(combinationError) || Boolean(amountError)} onClick={saveCorrection}>{saving ? "Saving..." : "Save correction"}</button></>}>
        {selected && (
          <>
            <section className="detail-section"><h3>Ledger identity</h3><dl className="detail-list"><dt>Stable ID</dt><dd>{selected.id}</dd><dt>Import batch</dt><dd>{selected.importBatchId ?? "Manual lineage unavailable"}</dd><dt>Amount</dt><dd className="num">{formatMoney(selected.amountMinor, selected.currency)}</dd></dl></section>
            <section className="detail-section"><h3>Correction</h3><div className="form-grid">
              <Field label={`Amount (${selected.currency})`} htmlFor="edit-amount" error={amountError}>{(accessibility) => <input {...accessibility} id="edit-amount" inputMode="decimal" value={edit.amount} onChange={(event) => setEdit((current) => ({ ...current, amount: event.target.value }))} />}</Field>
              <Field label="Category" htmlFor="edit-category"><select id="edit-category" value={edit.categoryId} onChange={(event) => setEdit({ amount: edit.amount, categoryId: event.target.value, subcategoryId: "" })}><option value="">Uncategorized</option>{categories.data?.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
               <Field label="Subcategory" htmlFor="edit-subcategory" error={combinationError}>{(accessibility) => <select {...accessibility} id="edit-subcategory" value={edit.subcategoryId} disabled={!edit.categoryId} onChange={(event) => setEdit((current) => ({ ...current, subcategoryId: event.target.value }))}><option value="">None</option>{subcategories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}</Field>
            </div></section>
            {saveError && <InlineNotice tone="bad">{saveError}</InlineNotice>}
          </>
        )}
      </Drawer>
    </>
  );
}
