import { useState, type FormEvent } from "react";
import { FilePlus2, RotateCcw, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import type { ImportBatch } from "../api/types";
import { Drawer } from "../components/Drawer";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { AccountForm } from "../features/accounts/AccountForm";
import { useResource } from "../hooks/use-resource";
import { formatDate } from "../shared/format";

const drafts = new Set(["UPLOADED", "AWAITING_MAPPING", "STAGING", "PARSED", "NEEDS_REVIEW", "READY"]);
function ImportRow({ batch, onDelete }: { batch: ImportBatch; onDelete: (batch: ImportBatch) => void }) {
  const resumable = drafts.has(batch.status);
  return (
    <article className="import-row">
      <div><h3>{batch.filename}</h3><p>Created {formatDate(batch.createdAt)} / {batch.totalRows} rows</p></div>
      <StatusBadge tone={batch.status === "FAILED" ? "bad" : batch.status === "COMMITTED" ? "good" : batch.needsReviewRows ? "warn" : "neutral"}>{batch.status.replaceAll("_", " ")}</StatusBadge>
      <span>{batch.needsReviewRows} need review</span>
      <div className="import-row-actions">
        {resumable && <Link className="button secondary" to={`/imports/${batch.id}`}><RotateCcw aria-hidden="true" /> Resume</Link>}
        {batch.status === "COMMITTED" && <Link className="button secondary" to={`/imports/${batch.id}`}>View audit rows</Link>}
        {resumable && <button className="icon-button" aria-label={`Delete ${batch.filename}`} onClick={() => onDelete(batch)}><Trash2 aria-hidden="true" /></button>}
      </div>
    </article>
  );
}

export default function ImportPage() {
  const navigate = useNavigate();
  const accounts = useResource(() => api.accounts.list(), "import-accounts");
  const imports = useResource(() => api.imports.list(), "import-list");
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<ImportBatch | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [creatingAccount, setCreatingAccount] = useState(false);
  const activeAccounts = accounts.data?.filter((account) => account.active) ?? [];
  const draftItems = imports.data?.filter((item) => drafts.has(item.status)) ?? [];
  const historyItems = imports.data?.filter((item) => !drafts.has(item.status) && item.status !== "DELETED") ?? [];

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!accountId || !file) {
      setUploadError("Choose an account and one statement file before parsing.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploaded(null);
    try {
      const batch = await api.imports.upload(accountId, file);
      setUploaded(batch);
      imports.reload();
      navigate(`/imports/${batch.id}`);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "The statement could not be parsed.");
      imports.reload();
    } finally {
      setUploading(false);
    }
  }

  async function remove(batch: ImportBatch) {
    if (!window.confirm(`Hide draft "${batch.filename}"? This soft-deletes the batch from normal views; retained data is not purged.`)) return;
    setDeletingId(batch.id);
    try {
       await api.imports.delete(batch.id, batch.revision);
      imports.reload();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "The draft could not be deleted.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Tabular ingestion" title="Import" description="Choose any active destination account and one CSV, XLS, or XLSX file. The original stays attached to its draft while you inspect, map, review, and commit." />
      <ol className="workflow workflow-five" aria-label="Import workflow">
        {[{ title: "Select", detail: "Destination account and file" }, { title: "Inspect", detail: "Confirm table structure" }, { title: "Map", detail: "Translate source columns" }, { title: "Review", detail: "Resolve rows and duplicates" }, { title: "Commit", detail: "Write accepted rows" }].map((step, index) => (
          <li key={step.title} data-step={index + 1} className={`workflow-step ${index === 0 ? "active" : ""}`} aria-current={index === 0 ? "step" : undefined}>
            <strong>{step.title}</strong><span>{step.detail}</span>
          </li>
        ))}
      </ol>

      <section className="ledger-panel panel-padding" aria-labelledby="new-import-title">
        <div className="section-heading"><h2 id="new-import-title">New tabular import</h2><p>CSV, XLS, or XLSX</p></div>
        {accounts.loading ? <LoadingState label="Loading destination accounts" /> : accounts.error ? <ErrorState error={accounts.error} retry={accounts.reload} /> : (
          <form onSubmit={upload} noValidate>
            <Field label="Destination account" htmlFor="import-account">
              <select id="import-account" value={accountId} onChange={(event) => { if (event.target.value === "__create__") { setCreatingAccount(true); return; } setAccountId(event.target.value); }} required>
                <option value="">Choose account</option>
                {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                <option value="__create__">Create new account</option>
              </select>
            </Field>
            {!activeAccounts.length && <InlineNotice tone="warn">Create an account here before uploading a file.</InlineNotice>}
            <div className="upload-zone">
              <div><FilePlus2 aria-hidden="true" /><h3>One transaction table</h3><p>Upload any CSV, XLS, or XLSX export. You will inspect and map its columns before rows are staged.</p><input className="statement-file-input sr-only" id="statement-file" aria-label="Statement file" type="file" accept=".csv,.xls,.xlsx,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><label className="file-picker" htmlFor="statement-file"><span className="file-picker-action"><FilePlus2 aria-hidden="true" /> Choose file</span><span className="file-picker-name" aria-live="polite">{file?.name ?? "No file chosen"}</span></label></div>
            </div>
            {uploading && <InlineNotice>Uploading and inspecting the file locally. Keep this page open.</InlineNotice>}
            {uploadError && <InlineNotice tone="bad">{uploadError}</InlineNotice>}
            {uploaded && (
              <InlineNotice tone={uploaded.needsReviewRows ? "warn" : "good"}>
                Draft created. <Link to={`/imports/${uploaded.id}`}>Continue inspection and mapping</Link>.
              </InlineNotice>
            )}
            <div className="form-actions"><button className="button" type="submit" disabled={uploading}>{uploading ? "Inspecting..." : "Upload and inspect"}</button><span className="field-hint">Files stay private in your mounted data directory.</span></div>
          </form>
        )}
      </section>

      <div className="two-column" style={{ marginTop: "3rem" }}>
        <section><div className="section-heading"><h2>Drafts</h2><p>Persistent and resumable</p></div>{imports.loading ? <LoadingState label="Loading import drafts" /> : imports.error ? <ErrorState error={imports.error} retry={imports.reload} /> : draftItems.length ? <div className="import-list">{draftItems.map((item) => <ImportRow key={item.id} batch={item} onDelete={remove} />)}</div> : <EmptyState title="No open drafts" description="Uploaded and manual drafts that still need review will remain here." />}</section>
        <section><div className="section-heading"><h2>History</h2><p>Committed and failed runs</p></div>{historyItems.length ? <div className="import-list">{historyItems.map((item) => <ImportRow key={item.id} batch={item} onDelete={remove} />)}</div> : <EmptyState title="No import history" description="Committed batches and failed parsing attempts will be visible here." />}</section>
      </div>
      {deletingId && <span className="sr-only" role="status">Deleting draft {deletingId}</span>}
      <Drawer open={creatingAccount} title="Create new account" description="The new account will be selected for this import." onClose={() => setCreatingAccount(false)}>
        <AccountForm onCreated={(account) => { accounts.reload(); setAccountId(account.id); setCreatingAccount(false); }} />
      </Drawer>
    </>
  );
}
