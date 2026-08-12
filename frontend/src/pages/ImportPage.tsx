import { useState, type FormEvent } from "react";
import { FilePlus2, RotateCcw, Trash2 } from "lucide-react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { ImportBatch } from "../api/types";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { importSourceConfig, supportedImportProviders } from "../features/imports/source-config";
import { useResource } from "../hooks/use-resource";
import { formatDate } from "../shared/format";

const drafts = new Set(["UPLOADED", "PARSED", "NEEDS_REVIEW", "READY"]);
function ImportRow({ batch, onDelete }: { batch: ImportBatch; onDelete: (batch: ImportBatch) => void }) {
  const resumable = drafts.has(batch.status);
  return (
    <article className="import-row">
      <div><h3>{batch.filename}</h3><p>Created {formatDate(batch.createdAt)} / {batch.totalRows} rows</p></div>
      <StatusBadge tone={batch.status === "FAILED" ? "bad" : batch.status === "COMMITTED" ? "good" : batch.needsReviewRows ? "warn" : "neutral"}>{batch.status.replaceAll("_", " ")}</StatusBadge>
      <span>{batch.needsReviewRows} need review</span>
      <div className="import-row-actions">
        {resumable && <Link className="button secondary" to={`/imports/${batch.id}`}><RotateCcw aria-hidden="true" /> Resume</Link>}
        {resumable && <button className="icon-button" aria-label={`Delete ${batch.filename}`} onClick={() => onDelete(batch)}><Trash2 aria-hidden="true" /></button>}
      </div>
    </article>
  );
}

export default function ImportPage() {
  const accounts = useResource(() => api.sourceAccounts.list(), "import-accounts");
  const imports = useResource(() => api.imports.list(), "import-list");
  const [sourceAccountId, setSourceAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<ImportBatch | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const activeAccounts = accounts.data?.filter((account) => account.active && supportedImportProviders.has(account.provider.toUpperCase())) ?? [];
  const selectedAccount = activeAccounts.find((account) => account.id === sourceAccountId);
  const sourceConfig = selectedAccount ? importSourceConfig(selectedAccount.provider) : null;
  const draftItems = imports.data?.filter((item) => drafts.has(item.status)) ?? [];
  const historyItems = imports.data?.filter((item) => !drafts.has(item.status) && item.status !== "DELETED") ?? [];

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!sourceAccountId || !file) {
      setUploadError("Choose a source account and one statement file before parsing.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploaded(null);
    try {
      const batch = await api.imports.upload(sourceAccountId, file);
      setUploaded(batch);
      imports.reload();
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
      await api.imports.delete(batch.id);
      imports.reload();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "The draft could not be deleted.");
    } finally {
      setDeletingId(null);
    }
  }

  const activeStep = uploaded ? (uploaded.status === "READY" ? 4 : 3) : uploading ? 2 : 1;
  return (
    <>
      <PageHeader eyebrow="Statement ingestion" title="Import" description="Start one bounded import from one source and one file. The original stays attached to its draft while normalized rows move through review." />
      <ol className="workflow" aria-label="Import workflow">
        {[{ title: "Source / File", detail: "Identify one account and statement" }, { title: "Parse Summary", detail: "Validate format and duplicate file" }, { title: "Review", detail: "Resolve labels and likely matches" }, { title: "Commit", detail: "Write the accepted rows atomically" }].map((step, index) => (
          <li key={step.title} data-step={index + 1} className={`workflow-step ${index + 1 === activeStep ? "active" : index + 1 < activeStep ? "complete" : ""}`} aria-current={index + 1 === activeStep ? "step" : undefined}>
            <strong>{step.title}</strong><span>{step.detail}</span>
          </li>
        ))}
      </ol>

      <section className="ledger-panel panel-padding" aria-labelledby="new-import-title">
        <div className="section-heading"><h2 id="new-import-title">New statement</h2><p>Revolut, DBS, and Mastercard exports</p></div>
        {accounts.loading ? <LoadingState label="Loading source accounts" /> : accounts.error ? <ErrorState error={accounts.error} retry={accounts.reload} /> : !activeAccounts.length ? (
          <EmptyState title="No active source accounts" description="A source account must exist before a statement can be parsed." />
        ) : (
          <form onSubmit={upload} noValidate>
            <Field label="Source account" htmlFor="import-account">
              <select id="import-account" value={sourceAccountId} onChange={(event) => { setSourceAccountId(event.target.value); setFile(null); }} required>
                <option value="">Choose account</option>
                {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.displayName} / {account.provider}</option>)}
              </select>
            </Field>
            <div className="upload-zone">
              <div><FilePlus2 aria-hidden="true" /><h3>One statement file</h3><p>{sourceConfig?.help ?? "Choose a supported source account to see its accepted export formats."}</p><input className="statement-file-input sr-only" key={sourceAccountId} id="statement-file" aria-label="Statement file" type="file" accept={sourceConfig?.accept ?? ""} disabled={!sourceConfig} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><label className={`file-picker ${sourceConfig ? "" : "disabled"}`} htmlFor="statement-file" aria-disabled={!sourceConfig}><span className="file-picker-action"><FilePlus2 aria-hidden="true" /> Choose statement</span><span className="file-picker-name" aria-live="polite">{file?.name ?? (sourceConfig ? "No file chosen" : "Choose an account first")}</span></label></div>
            </div>
            {uploading && <InlineNotice>Parsing and checking the statement. Keep this page open.</InlineNotice>}
            {uploadError && <InlineNotice tone="bad">{uploadError}</InlineNotice>}
            {uploaded && (
              <InlineNotice tone={uploaded.needsReviewRows ? "warn" : "good"}>
                Parsed {uploaded.totalRows} rows: {uploaded.validRows} valid, {uploaded.needsReviewRows} need review, and {uploaded.duplicateRows} duplicate candidates. <Link to={`/imports/${uploaded.id}`}>Open review</Link>.
              </InlineNotice>
            )}
            <div className="form-actions"><button className="button" type="submit" disabled={uploading}>{uploading ? "Parsing..." : "Upload and parse"}</button><span className="field-hint">Files stay private in your mounted data directory.</span></div>
          </form>
        )}
      </section>

      <div className="two-column" style={{ marginTop: "3rem" }}>
        <section><div className="section-heading"><h2>Drafts</h2><p>Persistent and resumable</p></div>{imports.loading ? <LoadingState label="Loading import drafts" /> : imports.error ? <ErrorState error={imports.error} retry={imports.reload} /> : draftItems.length ? <div className="import-list">{draftItems.map((item) => <ImportRow key={item.id} batch={item} onDelete={remove} />)}</div> : <EmptyState title="No open drafts" description="Uploaded and manual drafts that still need review will remain here." />}</section>
        <section><div className="section-heading"><h2>History</h2><p>Committed and failed runs</p></div>{historyItems.length ? <div className="import-list">{historyItems.map((item) => <ImportRow key={item.id} batch={item} onDelete={remove} />)}</div> : <EmptyState title="No import history" description="Committed batches and failed parsing attempts will be visible here." />}</section>
      </div>
      {deletingId && <span className="sr-only" role="status">Deleting draft {deletingId}</span>}
    </>
  );
}
