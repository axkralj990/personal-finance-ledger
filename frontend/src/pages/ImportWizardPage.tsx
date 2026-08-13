import {
  useEffect,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  AlertTriangle,
  Download,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import type {
  Account,
  ImportBatch,
  ImportDiagnostic,
  ImportExecutionPlan,
  ImportInspection,
  ImportMappingTemplate,
  MappingPreview,
  MappingProposal,
} from "../api/types";
import {
  ErrorState,
  Field,
  InlineNotice,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "../components/ui";
import {
  dateFormatSuggestions,
  inferDateFormat,
  mappingErrors,
  mappingOriginLabel,
  universalPlan,
} from "../features/imports/mapping-plan";
import { useResource } from "../hooks/use-resource";
import ImportReviewPage from "./ImportReviewPage";

const reviewStatuses = new Set(["PARSED", "NEEDS_REVIEW"]);
const steps = ["Select", "Inspect", "Map", "Review", "Commit"] as const;
const previewPageSizes = [25, 50, 100] as const;

function stepFor(batch: ImportBatch, requested: string | null) {
  const mutable = !new Set(["COMMITTED", "FAILED", "DELETED", "STAGING"]).has(
    batch.status,
  );
  if (requested === "inspect" && mutable) return 2;
  if (requested === "map" && mutable) return 3;
  if (batch.status === "READY" || batch.status === "COMMITTED") return 5;
  if (reviewStatuses.has(batch.status)) return 4;
  if (batch.status === "STAGING") return 3;
  return 2;
}

function Workflow({ active }: { active: number }) {
  const notes = [
    "Account and file",
    "Table structure",
    "Canonical fields",
    "Rows and duplicates",
    "Ledger write",
  ];
  return (
    <ol className="workflow workflow-five" aria-label="Import workflow">
      {steps.map((title, index) => (
        <li
          key={title}
          data-step={index + 1}
          className={`workflow-step ${index + 1 === active ? "active" : index + 1 < active ? "complete" : ""}`}
          aria-current={index + 1 === active ? "step" : undefined}
        >
          <strong>{title}</strong>
          <span>{notes[index]}</span>
        </li>
      ))}
    </ol>
  );
}

export default function ImportWizardPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const batch = useResource(
    () => api.imports.detail(id),
    `import-wizard:${id}`,
  );
  const accounts = useResource(
    () => api.accounts.list(),
    "import-wizard-accounts",
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [batchSnapshot, setBatchSnapshot] = useState<ImportBatch | null>(null);
  const item =
    batchSnapshot?.id === id &&
    (!batch.data || batchSnapshot.revision >= batch.data.revision)
      ? batchSnapshot
      : batch.data;

  async function remove() {
    if (
      !item ||
      !window.confirm(
        `Delete draft "${item.filename}"? Retained import data follows the server's deletion policy.`,
      )
    )
      return;
    setDeleting(true);
    setActionError(null);
    try {
      await api.imports.delete(item.id, item.revision);
      navigate("/import");
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "The draft could not be deleted.",
      );
      setDeleting(false);
    }
  }

  async function commit() {
    if (!item) return;
    setCommitting(true);
    setActionError(null);
    try {
      await api.imports.commit(item.id, item.revision);
      navigate("/transactions");
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "The import could not be committed.",
      );
      batch.reload();
      setCommitting(false);
    }
  }

  if (batch.loading || accounts.loading)
    return (
      <>
        <PageHeader
          title="Import"
          description="Recovering the persisted import workflow."
        />
        <LoadingState label="Opening import draft" />
      </>
    );
  if (batch.error)
    return (
      <>
        <PageHeader
          title="Import"
          description="The import draft could not be opened."
        />
        <ErrorState error={batch.error} retry={batch.reload} />
      </>
    );
  if (accounts.error)
    return (
      <>
        <PageHeader
          title="Import"
          description="The destination account could not be loaded."
        />
        <ErrorState error={accounts.error} retry={accounts.reload} />
      </>
    );
  if (!item) return null;

  const active = stepFor(item, searchParams.get("step"));
  const account =
    accounts.data?.find((candidate) => candidate.id === item.accountId) ??
    null;
  const remapping = item.mappingRevision > 0;
  let body: ReactNode;
  if (item.status === "STAGING") body = <StagingStep reload={batch.reload} />;
  else if (active === 2 && item.status !== "COMMITTED")
    body = (
      <InspectionStep
        batch={item}
        onContinue={() => {
          batch.reload();
          setSearchParams({ step: "map", ...(remapping && { remap: "1" }) });
        }}
      />
    );
  else if (active === 3 && item.status !== "COMMITTED")
    body = (
      <MappingStep
        batch={item}
        account={account}
        onStaged={batch.reload}
        onBack={() =>
          setSearchParams({ step: "inspect", ...(remapping && { remap: "1" }) })
        }
      />
    );
  else if (active === 4)
    body = (
      <ReviewStep
        batch={item}
        reload={batch.reload}
        onBatchChanged={setBatchSnapshot}
        remap={(step) => setSearchParams({ step, remap: "1" })}
      />
    );
  else if (active === 5 && item.status === "READY")
    body = (
      <CommitStep
        batch={item}
        committing={committing}
        commit={commit}
        remap={(step) => setSearchParams({ step, remap: "1" })}
      />
    );
  else if (item.status === "COMMITTED")
    body = (
      <>
        <InlineNotice tone="good">
          This import has been committed and is immutable. Its originating rows,
          including ignored transactions, remain available below for audit. {" "}
          <Link to="/transactions">View ledger transactions</Link>.
        </InlineNotice>
        <ImportReviewPage embedded readOnly />
      </>
    );
  else if (item.status === "FAILED")
    body = (
      <InlineNotice tone="bad">
        {item.errors.join(" ") || "The file could not be imported."}
      </InlineNotice>
    );
  else body = null;

  return (
    <>
      <PageHeader
        eyebrow={`Import / ${item.status.replaceAll("_", " ")}`}
        title={item.filename}
        description={`Destination: ${account?.name ?? "Unknown account"}. This draft is persisted after every server-confirmed step.`}
        actions={
          <>
            <Link className="button secondary" to="/import">
              Back to imports
            </Link>
            {!new Set(["COMMITTED", "FAILED", "DELETED"]).has(item.status) && (
              <button
                className="button danger"
                disabled={deleting}
                onClick={remove}
              >
                <Trash2 aria-hidden="true" />{" "}
                {deleting ? "Deleting..." : "Delete draft"}
              </button>
            )}
          </>
        }
      />
      <Workflow active={active} />
      <div aria-live="assertive">
        {actionError && <InlineNotice tone="bad">{actionError}</InlineNotice>}
      </div>
      <Diagnostics
        diagnostics={item.mappingDiagnostics}
        title="Mapping diagnostics"
      />
      {body}
    </>
  );
}

function InspectionStep({
  batch,
  onContinue,
}: {
  batch: ImportBatch;
  onContinue: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(25);
  const [inspection, setInspection] = useState<ImportInspection | null>(null);
  const [revision, setRevision] = useState(batch.revision);
  const [headerDraft, setHeaderDraft] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  function reloadInspection() {
    setLoading(true);
    setError(null);
    setReloadNonce((value) => value + 1);
  }

  useEffect(() => {
    let active = true;
    void api.imports
      .inspection(batch.id, { offset, limit })
      .then(
        (result) => {
          if (active) {
            setInspection(result);
            setRevision(result.batchRevision);
            setHeaderDraft(result.headerRow);
            setError(null);
          }
        },
        (caught: unknown) => {
          if (active)
            setError(
              caught instanceof Error
                ? caught.message
                : "Inspection could not be loaded.",
            );
        },
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [batch.id, limit, offset, reloadNonce]);

  async function updateSelection(selectedSheet: string, headerRow: number) {
    if (
      !inspection ||
      saving ||
      (selectedSheet === inspection.selectedSheet &&
        headerRow === inspection.headerRow)
    )
      return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.imports.patchInspection(batch.id, {
        expectedRevision: revision,
        selectedSheet,
        headerRow,
        previewOffset: 0,
        previewLimit: limit,
        confirmRestaging: batch.mappingRevision > 0,
      });
      setInspection(updated);
      setRevision(updated.batchRevision);
      setHeaderDraft(updated.headerRow);
      setOffset(0);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Inspection choices could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading && !inspection)
    return <LoadingState label="Loading local file inspection" />;
  if (error && !inspection)
    return (
      <ErrorState
        error={new Error(error)}
        retry={reloadInspection}
      />
    );
  if (!inspection) return null;
  const pageEnd = Math.min(
    inspection.rowCount,
    offset + inspection.preview.length,
  );
  return (
    <section className="import-stage ledger-panel panel-padding">
      <div className="section-heading">
        <h2>Inspect source table</h2>
        <p>
          {inspection.fileType} / {inspection.rowCount} data rows
        </p>
      </div>
      {batch.mappingRevision > 0 && (
        <InlineNotice tone="warn">
          <AlertTriangle aria-hidden="true" /> Changing sheet or header
          immediately discards staged review rows and requires a new mapping.
        </InlineNotice>
      )}
      <div className="form-grid">
        <Field label="Sheet" htmlFor="inspection-sheet">
          <select
            id="inspection-sheet"
            disabled={saving}
            value={inspection.selectedSheet}
            onChange={(event) => {
              const sheet = inspection.sheets.find(
                (item) => item.name === event.target.value,
              );
              void updateSelection(
                event.target.value,
                sheet?.candidateHeaderRows[0] ?? 1,
              );
            }}
          >
            {inspection.sheets.map((sheet) => (
              <option key={`${sheet.index}-${sheet.name}`} value={sheet.name}>
                {sheet.name} ({sheet.rowCount} rows)
              </option>
            ))}
          </select>
        </Field>
        <Field label="Header row" htmlFor="inspection-header">
          <input
            id="inspection-header"
            type="number"
            min={1}
            disabled={saving}
            value={headerDraft ?? inspection.headerRow}
            onChange={(event) => {
              const next = Number(event.target.value);
              setHeaderDraft(next);
              if (next >= 1)
                void updateSelection(inspection.selectedSheet, next);
            }}
          />
        </Field>
      </div>
      <div className="inspection-facts">
        <StatusBadge>{inspection.columns.length} columns</StatusBadge>
        {inspection.encoding && (
          <StatusBadge>{inspection.encoding}</StatusBadge>
        )}
        {inspection.delimiter && (
          <StatusBadge>
            Delimiter {JSON.stringify(inspection.delimiter)}
          </StatusBadge>
        )}
        <StatusBadge
          tone={inspection.possibleFooterRows.length ? "warn" : "neutral"}
        >
          {inspection.possibleFooterRows.length} possible footer rows
        </StatusBadge>
        <StatusBadge
          tone={inspection.repeatedHeaderRows.length ? "warn" : "neutral"}
        >
          {inspection.repeatedHeaderRows.length} repeated headers
        </StatusBadge>
      </div>
      <RawPreview inspection={inspection} />
      <PreviewPagination
        offset={offset}
        limit={limit}
        total={inspection.rowCount}
        shownEnd={pageEnd}
        onOffset={setOffset}
        onLimit={(value) => {
          setLimit(value);
          setOffset(0);
        }}
        label="raw rows"
      />
      <Diagnostics
        diagnostics={inspection.diagnostics}
        title="Inspection diagnostics"
      />
      <div aria-live="assertive">
        {saving && <p className="notice">Reloading the source preview...</p>}
        {error && <InlineNotice tone="bad">{error}</InlineNotice>}
      </div>
      <div className="form-actions">
        <button className="button" disabled={saving} onClick={onContinue}>
          Confirm table and map columns
        </button>
        <a
          className="button secondary"
          href={api.imports.sourceFileUrl(batch.id)}
        >
          <Download aria-hidden="true" /> Download original
        </a>
      </div>
    </section>
  );
}

function RawPreview({ inspection }: { inspection: ImportInspection }) {
  return (
    <div
      className="preview-scroll"
      tabIndex={0}
      aria-label="Raw source preview"
    >
      <table className="preview-table">
        <thead>
          <tr>
            <th>Row</th>
            {inspection.columns.map((column) => (
              <th key={column.id}>
                <strong>{column.rawLabel || "Untitled"}</strong>
                <small>
                  {column.id} / {column.inferredType.toLowerCase()}
                </small>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {inspection.preview.map((row) => (
            <tr key={row.rowNumber}>
              <th>{row.rowNumber}</th>
              {inspection.columns.map((column) => (
                <td key={column.id}>{String(row.values[column.id] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MappingStep({
  batch,
  account,
  onStaged,
  onBack,
}: {
  batch: ImportBatch;
  account: Account | null;
  onStaged: () => void;
  onBack: () => void;
}) {
  const inspection = useResource(
    () => api.imports.inspection(batch.id, { limit: 25 }),
    `mapping-inspection:${batch.id}:${batch.revision}`,
  );
  if (inspection.loading)
    return <LoadingState label="Preparing mapping controls" />;
  if (inspection.error)
    return <ErrorState error={inspection.error} retry={inspection.reload} />;
  if (!inspection.data) return null;
  return (
    <MappingForm
      key={`${batch.id}:${inspection.data.structuralSignature}:${batch.mappingRevision}`}
      batch={batch}
      account={account}
      inspection={inspection.data}
      onStaged={onStaged}
      onBack={onBack}
    />
  );
}

function proposalKey(proposal: MappingProposal) {
  if (proposal.templateId)
    return `template:${proposal.templateId}:${proposal.templateVersionId}`;
  return "inferred";
}

function MappingForm({
  batch,
  account,
  inspection,
  onStaged,
  onBack,
}: {
  batch: ImportBatch;
  account: Account | null;
  inspection: ImportInspection;
  onStaged: () => void;
  onBack: () => void;
}) {
  const inferredProposal: MappingProposal | null = inspection.proposals.universal
    ? {
        origin: "MANUAL",
        label: "Inferred universal mapping",
        plan: inspection.proposals.universal,
        templateId: null,
        templateVersionId: null,
        scope: null,
      }
    : null;
  const proposals = [
    ...(inferredProposal ? [inferredProposal] : []),
    ...inspection.proposals.templates,
  ];
  const currentProposal: MappingProposal | null = batch.currentMapping
    ? {
        origin: batch.currentMappingOrigin ?? "MANUAL",
        label: `Confirmed mapping revision ${batch.mappingRevision}`,
        plan: batch.currentMapping,
        templateId: batch.currentTemplateId,
        templateVersionId: batch.currentTemplateVersionId,
        scope: null,
      }
    : null;
  const initial = currentProposal ?? proposals[0] ?? null;
  const [selectedKey, setSelectedKey] = useState(
    currentProposal ? "current" : initial ? proposalKey(initial) : "manual",
  );
  const [plan, setPlan] = useState<ImportExecutionPlan>(() =>
    universalPlan(
      initial?.plan ?? null,
      inspection,
      account?.defaultCurrency ?? "",
    ),
  );
  const [templateRef, setTemplateRef] = useState<{
    id: string;
    versionId: string;
  } | null>(
    initial?.templateId && initial.templateVersionId
      ? { id: initial.templateId, versionId: initial.templateVersionId }
      : null,
  );
  const [revision, setRevision] = useState(
    Math.max(batch.revision, inspection.batchRevision),
  );
  const [preview, setPreview] = useState<MappingPreview | null>(null);
  const [previewOffset, setPreviewOffset] = useState(0);
  const [previewLimit, setPreviewLimit] = useState(25);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [payload, setPayload] = useState<Awaited<
    ReturnType<typeof api.imports.mappingSuggestionPayload>
  > | null>(null);
  const [consent, setConsent] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const errors = mappingErrors(plan);

  useEffect(() => {
    if (errors.length) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setPreviewing(true);
      void api.imports
        .previewMapping(batch.id, plan, {
          offset: previewOffset,
          limit: previewLimit,
        })
        .then(
          (result) => {
            if (active) {
              setPreview(result);
              setError(null);
            }
          },
          (caught: unknown) => {
            if (active) {
              setPreview(null);
              setError(
                caught instanceof Error
                  ? caught.message
                  : "The mapping preview failed.",
              );
            }
          },
        )
        .finally(() => {
          if (active) setPreviewing(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [batch.id, plan, errors.length, previewLimit, previewOffset]);

  const columns = inspection.columns;
  const label = (columnId: string) =>
    columns.find((column) => column.id === columnId)?.rawLabel || columnId;
  const options = (optional = false) => (
    <>
      {optional && <option value="">Not mapped</option>}
      {columns.map((column) => (
        <option value={column.id} key={column.id}>
          {column.rawLabel || "Untitled"} ({column.id})
        </option>
      ))}
    </>
  );
  const editPlan = (update: SetStateAction<ImportExecutionPlan>) => {
    setPlan((current) => {
      const next = typeof update === "function" ? update(current) : update;
      return next;
    });
    setSelectedKey("manual");
    setTemplateRef(null);
    setPreviewOffset(0);
  };
  const selectProposal = (
    proposal: MappingProposal,
    key = proposalKey(proposal),
  ) => {
    setSelectedKey(key);
    setPlan(proposal.plan);
    setTemplateRef(
      proposal.templateId && proposal.templateVersionId
        ? { id: proposal.templateId, versionId: proposal.templateVersionId }
        : null,
    );
    setPreviewOffset(0);
  };
  const selectTemplate = (template: ImportMappingTemplate) =>
    selectProposal({
      origin: template.origin,
      label: template.name,
      plan: template.currentVersion.plan,
      templateId: template.id,
      templateVersionId: template.currentVersion.id,
      scope: template.accountId ? "ACCOUNT" : "GLOBAL",
    });

  async function disclosePayload() {
    setError(null);
    try {
      const disclosed = await api.imports.mappingSuggestionPayload(batch.id);
      setPayload(disclosed);
      setRevision(disclosed.revision);
      setConsent(false);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "OpenAI mapping is unavailable. Manual mapping remains available.",
      );
    }
  }

  async function suggest() {
    if (!payload || !consent) return;
    setSuggesting(true);
    setError(null);
    try {
      const result = await api.imports.suggestMapping(batch.id, {
        expectedRevision: payload.revision,
        digest: payload.digest,
        consent: true,
      });
      setRevision(result.revision);
      setPayload(null);
      setConsent(false);
      if (result.plan) {
        setPlan(result.plan);
        setSelectedKey("openai");
        setTemplateRef(null);
        setPreviewOffset(0);
      } else
        setError(
          `${result.fallback?.message ?? "OpenAI did not return a usable mapping."} Manual mapping remains available.`,
        );
    } catch (caught) {
      setError(
        `${caught instanceof Error ? caught.message : "OpenAI mapping failed."} Manual mapping remains available.`,
      );
    } finally {
      setSuggesting(false);
    }
  }

  async function confirmAndStage() {
    if (errors.length || !preview || preview.importableRows < 1) return;
    if (
      batch.mappingRevision > 0 &&
      !window.confirm(
        "Restaging replaces all staged rows and discards row-level review edits. Continue?",
      )
    )
      return;
    setSaving(true);
    setError(null);
    try {
      const confirmed = await api.imports.confirmMapping(batch.id, {
        plan,
        expectedRevision: revision,
        templateId: templateRef?.id,
        templateVersionId: templateRef?.versionId,
        confirmRestaging: batch.mappingRevision > 0,
      });
      setRevision(confirmed.revision);
      await api.imports.stage(
        batch.id,
        confirmed.revision,
        confirmed.mappingRevision,
      );
      onStaged();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The mapping could not be staged.",
      );
      onStaged();
    } finally {
      setSaving(false);
    }
  }

  const displayedOrigin =
    selectedKey === "openai"
      ? "LLM_CONFIRMED"
      : templateRef
        ? (inspection.proposals.templates.find(
            (item) => item.templateId === templateRef.id,
          )?.origin ?? "MANUAL")
        : "MANUAL";
  return (
    <section className="import-stage">
      <div className="mapping-heading">
        <div>
          <p className="eyebrow">Mapping origin</p>
          <h2>{mappingOriginLabel(displayedOrigin)}</h2>
          <p className="page-intro">
            Every source uses the same universal mapping. Editing a saved
            mapping detaches its immutable template version.
          </p>
        </div>
        <StatusBadge
          tone={errors.length ? "bad" : preview?.errorRows ? "warn" : "good"}
        >
          {errors.length
            ? `${errors.length} mapping issues`
            : previewing
              ? "Validating"
              : `${preview?.importableRows ?? 0} importable rows`}
        </StatusBadge>
      </div>
      {batch.mappingRevision > 0 && (
        <InlineNotice tone="warn">
          <AlertTriangle aria-hidden="true" /> Remapping and staging will
          replace staged rows and discard review edits.
        </InlineNotice>
      )}
      <ProposalPicker
        proposals={proposals}
        current={currentProposal}
        selectedKey={selectedKey}
        onSelect={selectProposal}
        onManual={() => {
          setPlan(
            universalPlan(null, inspection, account?.defaultCurrency ?? ""),
          );
          setSelectedKey("manual");
          setTemplateRef(null);
        }}
      />
      <div className="mapping-layout">
        <div className="mapping-fields">
          <MappingControls
            plan={plan}
            setPlan={editPlan}
            options={options}
            label={label}
            inspection={inspection}
          />
        </div>
        <aside className="mapping-preview">
          <div className="mapping-preview-header">
            <div>
              <p className="eyebrow">Live validation</p>
              <h2>Raw and parsed</h2>
            </div>
            {previewing && (
              <RefreshCw className="spin" aria-label="Refreshing preview" />
            )}
          </div>
          <RawPreview inspection={inspection} />
          <ParsedPreview preview={errors.length ? null : preview} />
          <PreviewPagination
            offset={previewOffset}
            limit={previewLimit}
            total={preview?.totalRows ?? 0}
            shownEnd={Math.min(
              preview?.totalRows ?? 0,
              previewOffset + (preview?.rows.length ?? 0),
            )}
            onOffset={setPreviewOffset}
            onLimit={(value) => {
              setPreviewLimit(value);
              setPreviewOffset(0);
            }}
            label="mapped rows"
          />
          <div aria-live="polite">
            {errors.map((message) => (
              <InlineNotice tone="bad" key={message}>
                {message}
              </InlineNotice>
            ))}
          </div>
        </aside>
      </div>
      <section className="openai-boundary">
        <div>
          <p className="eyebrow">Optional inference</p>
          <h2>Suggest mapping with OpenAI</h2>
          <p>
            OpenAI never runs automatically. Only the exact redacted payload
            shown below is eligible to leave this server. Headers are sent
            verbatim and may themselves contain sensitive text.
          </p>
        </div>
        <button className="button secondary" onClick={disclosePayload}>
          <Sparkles aria-hidden="true" /> Suggest mapping with OpenAI
        </button>
      </section>
      {payload && (
        <div className="consent-panel">
          <InlineNotice tone="warn">
            <AlertTriangle aria-hidden="true" /> Column headers are not
            redacted. Review every header before consenting.
          </InlineNotice>
          <dl className="detail-list">
            <dt>SHA-256 digest</dt>
            <dd className="digest">{payload.digest}</dd>
            <dt>Batch revision</dt>
            <dd>{payload.revision}</dd>
          </dl>
          <pre className="raw-data consent-payload">
            {JSON.stringify(payload.payload, null, 2)}
          </pre>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
            />{" "}
            I reviewed this exact payload and consent to sending it to OpenAI.
          </label>
          <button
            className="button"
            disabled={!consent || suggesting}
            onClick={suggest}
          >
            {suggesting
              ? "Requesting suggestion..."
              : "Consent and request suggestion"}
          </button>
        </div>
      )}
      <TemplateManager
        batch={batch}
        inspection={inspection}
        account={account}
        plan={plan}
        sourceRevision={revision}
        openAiPlan={selectedKey === "openai"}
        onSelect={selectTemplate}
      />
      <Diagnostics
        diagnostics={batch.mappingDiagnostics}
        title="Current mapping diagnostics"
      />
      <div aria-live="assertive">
        {error && <InlineNotice tone="bad">{error}</InlineNotice>}
      </div>
      <div className="form-actions">
        <button
          className="button"
          disabled={
            saving ||
            previewing ||
            errors.length > 0 ||
            !preview ||
            preview.importableRows < 1
          }
          onClick={confirmAndStage}
        >
          {saving
            ? "Confirming and staging..."
            : "Confirm mapping and stage rows"}
        </button>
        <button className="button secondary" onClick={onBack}>
          Back to inspection
        </button>
        <span className="field-hint">
          Batch revision {revision}.{" "}
          {preview
            ? `${preview.importableRows} importable, ${preview.errorRows} errors, ${preview.auditRows} audit-only.`
            : "Waiting for a valid preview."}
        </span>
      </div>
    </section>
  );
}

function ProposalPicker({
  proposals,
  current,
  selectedKey,
  onSelect,
  onManual,
}: {
  proposals: MappingProposal[];
  current: MappingProposal | null;
  selectedKey: string;
  onSelect: (proposal: MappingProposal, key?: string) => void;
  onManual: () => void;
}) {
  return (
    <fieldset className="proposal-picker">
      <legend>Available mappings</legend>
      {current && (
        <label className="proposal-option">
          <input
            type="radio"
            name="mapping-proposal"
            checked={selectedKey === "current"}
            onChange={() => onSelect(current, "current")}
          />
          <span>
            <strong>{current.label}</strong>
            <small>
              {mappingOriginLabel(current.origin)} / recovered from batch
            </small>
          </span>
        </label>
      )}
      {proposals.map((proposal) => {
        const key = proposalKey(proposal);
        return (
          <label className="proposal-option" key={key}>
            <input
              type="radio"
              name="mapping-proposal"
              checked={selectedKey === key}
              onChange={() => onSelect(proposal)}
            />
            <span>
              <strong>{proposal.label}</strong>
              <small>
                {proposal.scope
                  ? `${proposal.scope.toLowerCase()} template`
                  : mappingOriginLabel(proposal.origin)}
                {proposal.templateVersionId
                  ? ` / version ${proposal.templateVersionId}`
                  : " / editable universal mapping"}
              </small>
            </span>
          </label>
        );
      })}
      <label className="proposal-option">
        <input
          type="radio"
          name="mapping-proposal"
          checked={selectedKey === "manual"}
          onChange={onManual}
        />
        <span>
          <strong>Blank editable mapping</strong>
          <small>Local universal mapping controls</small>
        </span>
      </label>
      {selectedKey === "openai" && (
        <label className="proposal-option">
          <input type="radio" name="mapping-proposal" checked readOnly />
          <span>
            <strong>OpenAI suggestion</strong>
            <small>Current audited suggestion</small>
          </span>
        </label>
      )}
    </fieldset>
  );
}

function MappingControls({
  plan,
  setPlan,
  options,
  label,
  inspection,
}: {
  plan: ImportExecutionPlan;
  setPlan: Dispatch<SetStateAction<ImportExecutionPlan>>;
  options: (optional?: boolean) => ReactNode;
  label: (id: string) => string;
  inspection: ImportInspection;
}) {
  const setOptional = (
    field: "sourceNativeId" | "categoryHint" | "subcategoryHint",
    sourceColumn: string,
  ) =>
    setPlan((current) => ({
      ...current,
      [field]: sourceColumn ? { sourceColumn } : null,
    }));
  const updateFilter = (
    index: number,
    patch: Partial<ImportExecutionPlan["exactFilters"][number]>,
  ) =>
    setPlan((current) => ({
      ...current,
      exactFilters: current.exactFilters.map((filter, filterIndex) =>
        filterIndex === index ? { ...filter, ...patch } : filter,
      ),
    }));
  return (
    <>
      <MappingCard
        title="Date and time"
        note="Map a date, a timestamp, or both."
      >
        <Field label="Transaction date" htmlFor="map-date">
          <select
            id="map-date"
            value={plan.transactionDate?.sourceColumn ?? ""}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                transactionDate: event.target.value
                  ? {
                      sourceColumn: event.target.value,
                      format: inferDateFormat(inspection, event.target.value),
                    }
                  : null,
              }))
            }
          >
            {options(true)}
          </select>
        </Field>
        <Field
          label="Date format"
          htmlFor="map-date-format"
          hint="Required strptime format, for example %d/%m/%Y"
        >
          <input
            id="map-date-format"
            list="mapping-date-formats"
            value={plan.transactionDate?.format ?? ""}
            disabled={!plan.transactionDate}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                transactionDate: current.transactionDate
                  ? {
                      ...current.transactionDate,
                      format: event.target.value,
                    }
                  : null,
              }))
            }
          />
        </Field>
        <Field label="Timestamp" htmlFor="map-timestamp">
          <select
            id="map-timestamp"
            value={plan.transactionTimestamp?.sourceColumn ?? ""}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                transactionTimestamp: event.target.value
                  ? {
                      sourceColumn: event.target.value,
                      format: inferDateFormat(inspection, event.target.value),
                      timezone: "UTC",
                    }
                  : null,
              }))
            }
          >
            {options(true)}
          </select>
        </Field>
        <Field
          label="Timestamp format"
          htmlFor="map-timestamp-format"
          hint="Required strptime format, including time directives when present"
        >
          <input
            id="map-timestamp-format"
            list="mapping-date-formats"
            disabled={!plan.transactionTimestamp}
            value={plan.transactionTimestamp?.format ?? ""}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                transactionTimestamp: current.transactionTimestamp
                  ? {
                      ...current.transactionTimestamp,
                      format: event.target.value,
                    }
                  : null,
              }))
            }
          />
        </Field>
        <datalist id="mapping-date-formats">
          {dateFormatSuggestions.map((format) => (
            <option value={format} key={format} />
          ))}
        </datalist>
        <Field
          label="Timestamp timezone"
          htmlFor="map-timezone"
          hint="IANA name or UTC"
        >
          <input
            id="map-timezone"
            disabled={!plan.transactionTimestamp}
            value={plan.transactionTimestamp?.timezone ?? "UTC"}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                transactionTimestamp: current.transactionTimestamp
                  ? {
                      ...current.transactionTimestamp,
                      timezone: event.target.value,
                    }
                  : null,
              }))
            }
          />
        </Field>
      </MappingCard>
      <MappingCard
        title="Description"
        note={
          plan.description.sourceColumn
            ? `Using ${label(plan.description.sourceColumn)}`
            : "Required field"
        }
      >
        <Field label="Description source" htmlFor="map-description">
          <select
            id="map-description"
            value={plan.description.sourceColumn}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                description: {
                  ...current.description,
                  sourceColumn: event.target.value,
                },
              }))
            }
          >
            <option value="">Choose column</option>
            {options()}
          </select>
        </Field>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={plan.description.strip}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                description: {
                  ...current.description,
                  strip: event.target.checked,
                },
              }))
            }
          />{" "}
          Strip leading and trailing whitespace
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={plan.description.collapseWhitespace}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                description: {
                  ...current.description,
                  collapseWhitespace: event.target.checked,
                },
              }))
            }
          />{" "}
          Collapse repeated whitespace
        </label>
      </MappingCard>
      <MappingCard
        title="Amount"
        note="Use one signed amount or separate debit and credit columns."
      >
        <Field label="Amount layout" htmlFor="map-amount-kind">
          <select
            id="map-amount-kind"
            value={plan.amount.kind}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                amount:
                  event.target.value === "signed"
                    ? {
                        kind: "signed",
                        sourceColumn: "",
                        numberFormat: current.amount.numberFormat,
                        signConvention: "EXPENSES_NEGATIVE",
                      }
                    : {
                        kind: "debit_credit",
                        debitColumn: "",
                        creditColumn: "",
                        numberFormat: current.amount.numberFormat,
                        debitSourceSign: "positive",
                        creditSourceSign: "positive",
                      },
              }))
            }
          >
            <option value="signed">Signed amount</option>
            <option value="debit_credit">Debit and credit columns</option>
          </select>
        </Field>
        {plan.amount.kind === "signed" ? (
          <>
            <Field label="Amount source" htmlFor="map-amount">
              <select
                id="map-amount"
                value={plan.amount.sourceColumn}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "signed"
                        ? {
                            ...current.amount,
                            sourceColumn: event.target.value,
                          }
                        : current.amount,
                  }))
                }
              >
                <option value="">Choose column</option>
                {options()}
              </select>
            </Field>
            <Field label="Expense sign convention" htmlFor="map-expense-sign">
              <select
                id="map-expense-sign"
                value={plan.amount.signConvention}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "signed"
                        ? {
                            ...current.amount,
                            signConvention: event.target.value as
                              | "EXPENSES_NEGATIVE"
                              | "EXPENSES_POSITIVE",
                          }
                        : current.amount,
                  }))
                }
              >
                <option value="EXPENSES_NEGATIVE">Expenses are negative</option>
                <option value="EXPENSES_POSITIVE">Expenses are positive</option>
              </select>
            </Field>
            <p className="field-hint">
              Negative expenses preserve source signs. Positive expenses invert every source sign.
            </p>
          </>
        ) : (
          <>
            <Field label="Debit source" htmlFor="map-debit">
              <select
                id="map-debit"
                value={plan.amount.debitColumn}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "debit_credit"
                        ? { ...current.amount, debitColumn: event.target.value }
                        : current.amount,
                  }))
                }
              >
                {options(true)}
              </select>
            </Field>
            <Field label="Credit source" htmlFor="map-credit">
              <select
                id="map-credit"
                value={plan.amount.creditColumn}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "debit_credit"
                        ? {
                            ...current.amount,
                            creditColumn: event.target.value,
                          }
                        : current.amount,
                  }))
                }
              >
                {options(true)}
              </select>
            </Field>
            <Field label="Debit source sign" htmlFor="map-debit-sign">
              <select
                id="map-debit-sign"
                value={plan.amount.debitSourceSign}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "debit_credit"
                        ? {
                            ...current.amount,
                            debitSourceSign: event.target.value as
                              | "positive"
                              | "negative",
                          }
                        : current.amount,
                  }))
                }
              >
                <option value="positive">Positive</option>
                <option value="negative">Negative</option>
              </select>
            </Field>
            <Field label="Credit source sign" htmlFor="map-credit-sign">
              <select
                id="map-credit-sign"
                value={plan.amount.creditSourceSign}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    amount:
                      current.amount.kind === "debit_credit"
                        ? {
                            ...current.amount,
                            creditSourceSign: event.target.value as
                              | "positive"
                              | "negative",
                          }
                        : current.amount,
                  }))
                }
              >
                <option value="positive">Positive</option>
                <option value="negative">Negative</option>
              </select>
            </Field>
          </>
        )}
        <NumberControls plan={plan} setPlan={setPlan} />
      </MappingCard>
      <MappingCard
        title="Currency"
        note="Read each row or apply one ISO currency."
      >
        <Field label="Currency mode" htmlFor="map-currency-kind">
          <select
            id="map-currency-kind"
            value={plan.currency.kind}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                currency:
                  event.target.value === "source"
                    ? { kind: "source", sourceColumn: "" }
                    : { kind: "constant", value: "EUR" },
              }))
            }
          >
            <option value="source">Source column</option>
            <option value="constant">Constant</option>
          </select>
        </Field>
        {plan.currency.kind === "source" ? (
          <Field label="Currency source" htmlFor="map-currency">
            <select
              id="map-currency"
              value={plan.currency.sourceColumn}
              onChange={(event) =>
                setPlan((current) => ({
                  ...current,
                  currency: {
                    kind: "source",
                    sourceColumn: event.target.value,
                  },
                }))
              }
            >
              <option value="">Choose column</option>
              {options()}
            </select>
          </Field>
        ) : (
          <Field label="Currency constant" htmlFor="map-currency-constant">
            <input
              id="map-currency-constant"
              maxLength={3}
              value={plan.currency.value}
              onChange={(event) =>
                setPlan((current) => ({
                  ...current,
                  currency: {
                    kind: "constant",
                    value: event.target.value.toUpperCase(),
                  },
                }))
              }
            />
          </Field>
        )}
      </MappingCard>
      <MappingCard
        title="Optional fields"
        note="Native IDs and taxonomy hints may be left unmapped."
      >
        {(
          [
            ["sourceNativeId", "Source native ID"],
            ["categoryHint", "Category hint"],
            ["subcategoryHint", "Subcategory hint"],
          ] as const
        ).map(([field, title]) => (
          <Field key={field} label={title} htmlFor={`map-${field}`}>
            <select
              id={`map-${field}`}
              value={plan[field]?.sourceColumn ?? ""}
              onChange={(event) => setOptional(field, event.target.value)}
            >
              {options(true)}
            </select>
          </Field>
        ))}
      </MappingCard>
      <MappingCard
        title="Rows and filters"
        note="All bounded row and exact-value controls are preserved."
      >
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={plan.skipEmptyRows}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                skipEmptyRows: event.target.checked,
              }))
            }
          />{" "}
          Skip empty rows
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={plan.skipRepeatedHeaders}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                skipRepeatedHeaders: event.target.checked,
              }))
            }
          />{" "}
          Skip exact repeated headers
        </label>
        <div className="form-grid">
          <Field label="First source row" htmlFor="map-first-row">
            <input
              id="map-first-row"
              type="number"
              min={1}
              value={plan.rowBounds.firstRow ?? ""}
              onChange={(event) =>
                setPlan((current) => ({
                  ...current,
                  rowBounds: {
                    ...current.rowBounds,
                    firstRow: event.target.value
                      ? Number(event.target.value)
                      : null,
                  },
                }))
              }
            />
          </Field>
          <Field label="Last source row" htmlFor="map-last-row">
            <input
              id="map-last-row"
              type="number"
              min={1}
              value={plan.rowBounds.lastRow ?? ""}
              onChange={(event) =>
                setPlan((current) => ({
                  ...current,
                  rowBounds: {
                    ...current.rowBounds,
                    lastRow: event.target.value
                      ? Number(event.target.value)
                      : null,
                  },
                }))
              }
            />
          </Field>
        </div>
        <div className="filter-list">
          {plan.exactFilters.map((filter, index) => (
            <section className="filter-rule" key={index}>
              <div className="form-grid">
                <Field
                  label={`Filter ${index + 1} column`}
                  htmlFor={`map-filter-column-${index}`}
                >
                  <select
                    id={`map-filter-column-${index}`}
                    value={filter.sourceColumn}
                    onChange={(event) =>
                      updateFilter(index, { sourceColumn: event.target.value })
                    }
                  >
                    {options()}
                  </select>
                </Field>
                <Field label="Mode" htmlFor={`map-filter-mode-${index}`}>
                  <select
                    id={`map-filter-mode-${index}`}
                    value={filter.mode}
                    onChange={(event) =>
                      updateFilter(index, {
                        mode: event.target.value as "include" | "exclude",
                      })
                    }
                  >
                    <option value="include">Include matching</option>
                    <option value="exclude">Exclude matching</option>
                  </select>
                </Field>
              </div>
              <Field
                label="Exact values, one per line"
                htmlFor={`map-filter-values-${index}`}
              >
                <textarea
                  id={`map-filter-values-${index}`}
                  value={filter.values.join("\n")}
                  onChange={(event) =>
                    updateFilter(index, {
                      values: event.target.value
                        .split("\n")
                        .map((value) => value.trim())
                        .filter(Boolean)
                        .slice(0, 50),
                    })
                  }
                />
              </Field>
              <button
                className="button ghost"
                onClick={() =>
                  setPlan((current) => ({
                    ...current,
                    exactFilters: current.exactFilters.filter(
                      (_, filterIndex) => filterIndex !== index,
                    ),
                  }))
                }
              >
                Remove filter
              </button>
            </section>
          ))}
        </div>
        <button
          className="button secondary"
          disabled={plan.exactFilters.length >= 16}
          onClick={() =>
            setPlan((current) => ({
              ...current,
              exactFilters: [
                ...current.exactFilters,
                {
                  sourceColumn: current.description.sourceColumn,
                  mode: "include",
                  values: [],
                },
              ],
            }))
          }
        >
          <Plus aria-hidden="true" /> Add exact filter
        </button>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={Boolean(plan.footerRule)}
            onChange={(event) =>
              setPlan((current) => ({
                ...current,
                footerRule: event.target.checked
                  ? {
                      sourceColumn: current.description.sourceColumn,
                      normalizedValue: "",
                    }
                  : null,
              }))
            }
          />{" "}
          Remove rows from an exact footer marker
        </label>
        {plan.footerRule && (
          <div className="form-grid">
            <Field label="Footer column" htmlFor="map-footer-column">
              <select
                id="map-footer-column"
                value={plan.footerRule.sourceColumn}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    footerRule: current.footerRule
                      ? {
                          ...current.footerRule,
                          sourceColumn: event.target.value,
                        }
                      : null,
                  }))
                }
              >
                {options()}
              </select>
            </Field>
            <Field label="Normalized footer marker" htmlFor="map-footer-value">
              <input
                id="map-footer-value"
                value={plan.footerRule.normalizedValue}
                onChange={(event) =>
                  setPlan((current) => ({
                    ...current,
                    footerRule: current.footerRule
                      ? {
                          ...current.footerRule,
                          normalizedValue: event.target.value,
                        }
                      : null,
                  }))
                }
              />
            </Field>
          </div>
        )}
      </MappingCard>
    </>
  );
}

function TemplateManager({
  batch,
  inspection,
  account,
  plan,
  sourceRevision,
  openAiPlan,
  onSelect,
}: {
  batch: ImportBatch;
  inspection: ImportInspection;
  account: Account | null;
  plan: ImportExecutionPlan;
  sourceRevision: number;
  openAiPlan: boolean;
  onSelect: (template: ImportMappingTemplate) => void;
}) {
  const [templates, setTemplates] = useState<ImportMappingTemplate[]>([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"ACCOUNT" | "GLOBAL">("ACCOUNT");
  const [selectedId, setSelectedId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [rename, setRename] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const selected =
    templates.find((template) => template.id === selectedId) ?? null;
  const reload = async () => {
    setLoading(true);
    try {
      setTemplates(
        await api.importMappings.list({
          accountId: account?.id,
          structuralSignature: inspection.structuralSignature,
          includeInactive: true,
        }),
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Mapping templates could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    let active = true;
    void api.importMappings
      .list({
        accountId: account?.id,
        structuralSignature: inspection.structuralSignature,
        includeInactive: true,
      })
      .then(
        (result) => {
          if (active) setTemplates(result);
        },
        (error: unknown) => {
          if (active)
            setMessage(
              error instanceof Error
                ? error.message
                : "Mapping templates could not be loaded.",
            );
        },
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [account?.id, inspection.structuralSignature]);

  async function create() {
    if (!name.trim()) return;
    setMessage(null);
    try {
      const created = await api.importMappings.create({
        name: name.trim(),
        structuralSignature: inspection.structuralSignature,
        accountId: scope === "ACCOUNT" ? (account?.id ?? null) : null,
        plan,
        ...(openAiPlan && {
          sourceBatchId: batch.id,
          sourceBatchRevision: sourceRevision,
        }),
      });
      setTemplates((current) => [...current, created]);
      setSelectedId(created.id);
      setSelectedVersionId(created.currentVersion.id);
      setRename(created.name);
      setName("");
      setMessage("Mapping template created.");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Mapping template could not be created.",
      );
    }
  }
  async function patch(input: {
    name?: string;
    active?: boolean;
    plan?: ImportExecutionPlan;
  }) {
    if (!selected) return;
    setMessage(null);
    try {
      const updated = await api.importMappings.patch(selected.id, {
        expectedRevision: selected.revision,
        ...input,
      });
      setTemplates((current) =>
        current.map((template) =>
          template.id === updated.id ? updated : template,
        ),
      );
      setSelectedVersionId(updated.currentVersion.id);
      setMessage(
        input.plan
          ? `Created template version ${updated.currentVersion.version}.`
          : "Template updated.",
      );
      if (input.plan) onSelect(updated);
    } catch (error) {
      await reload();
      setMessage(
        `${error instanceof Error ? error.message : "Template update conflicted."} The template list was reloaded.`,
      );
    }
  }
  return (
    <section className="template-manager">
      <div>
        <p className="eyebrow">Saved mapping library</p>
        <h2>Templates</h2>
        <p>
          Account templates are proposed before global templates. Existing
          versions remain immutable.
        </p>
      </div>
      <div className="template-manager-grid">
        <div>
          <Field label="Existing templates" htmlFor="template-select">
            <select
              id="template-select"
              disabled={loading}
              value={selectedId}
              onChange={(event) => {
                const id = event.target.value;
                setSelectedId(id);
                const summary = templates.find((item) => item.id === id);
                setRename(summary?.name ?? "");
                if (!id) {
                  setSelectedVersionId("");
                  return;
                }
                void api.importMappings.detail(id).then(
                  (detail) => {
                    setTemplates((current) =>
                      current.map((item) =>
                        item.id === detail.id ? detail : item,
                      ),
                    );
                    setSelectedVersionId(detail.currentVersion.id);
                    if (detail.active) onSelect(detail);
                  },
                  (error: unknown) =>
                    setMessage(
                      error instanceof Error
                        ? error.message
                        : "Template details could not be loaded.",
                    ),
                );
              }}
            >
              <option value="">Choose template</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} / v{template.currentVersion.version} /{" "}
                  {template.accountId ? "account" : "global"}
                  {template.active ? "" : " / inactive"}
                </option>
              ))}
            </select>
          </Field>
          {selected && (
            <div className="template-actions">
              <Field label="Version" htmlFor="template-version">
                <select
                  id="template-version"
                  value={selectedVersionId || selected.currentVersion.id}
                  onChange={(event) => {
                    setSelectedVersionId(event.target.value);
                    const version =
                      selected.versions.find(
                        (item) => item.id === event.target.value,
                      ) ?? selected.currentVersion;
                    if (selected.active)
                      onSelect({ ...selected, currentVersion: version });
                  }}
                >
                  {(selected.versions.length
                    ? selected.versions
                    : [selected.currentVersion]
                  ).map((version) => (
                    <option key={version.id} value={version.id}>
                      Version {version.version} / {version.createdAt}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Rename" htmlFor="template-rename">
                <input
                  id="template-rename"
                  value={rename}
                  onChange={(event) => setRename(event.target.value)}
                />
              </Field>
              <button
                className="button secondary"
                disabled={!rename.trim()}
                onClick={() => patch({ name: rename.trim() })}
              >
                Rename
              </button>
              <button
                className="button secondary"
                disabled={!selected.active}
                onClick={() => patch({ plan })}
              >
                Save controls as new version
              </button>
              <button
                className="button danger"
                onClick={() => patch({ active: !selected.active })}
              >
                {selected.active ? "Deactivate" : "Reactivate"}
              </button>
              <p className="field-hint">
                Revision {selected.revision}. Versions:{" "}
                {[...selected.versions]
                  .sort((a, b) => a.version - b.version)
                  .map((version) => `v${version.version}`)
                  .join(", ") || `v${selected.currentVersion.version}`}
                .
              </p>
            </div>
          )}
        </div>
        <div>
          <div className="form-grid">
            <Field label="New template name" htmlFor="template-name">
              <input
                id="template-name"
                maxLength={120}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="Scope" htmlFor="template-scope">
              <select
                id="template-scope"
                value={scope}
                onChange={(event) =>
                  setScope(event.target.value as "ACCOUNT" | "GLOBAL")
                }
              >
                <option value="ACCOUNT">This account</option>
                <option value="GLOBAL">All accounts</option>
              </select>
            </Field>
          </div>
          <button
            className="button secondary"
            disabled={!name.trim()}
            onClick={create}
          >
            Create template
          </button>
        </div>
      </div>
      <div aria-live="polite">
        {message && <p className="notice">{message}</p>}
      </div>
    </section>
  );
}

function MappingCard({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section className="mapping-card">
      <header>
        <h3>{title}</h3>
        <p>{note}</p>
      </header>
      <div className="mapping-card-fields">{children}</div>
    </section>
  );
}

function NumberControls({
  plan,
  setPlan,
}: {
  plan: ImportExecutionPlan;
  setPlan: Dispatch<SetStateAction<ImportExecutionPlan>>;
}) {
  const format = plan.amount.numberFormat;
  const update = (patch: Partial<typeof format>) =>
    setPlan((current) => ({
      ...current,
      amount: {
        ...current.amount,
        numberFormat: { ...current.amount.numberFormat, ...patch },
      },
    }));
  return (
    <>
      <div className="form-grid">
        <Field label="Decimal separator" htmlFor="map-decimal">
          <select
            id="map-decimal"
            value={format.decimalSeparator}
            onChange={(event) =>
              update({ decimalSeparator: event.target.value as "." | "," })
            }
          >
            <option value=".">Dot</option>
            <option value=",">Comma</option>
          </select>
        </Field>
        <Field label="Thousands separator" htmlFor="map-thousands">
          <select
            id="map-thousands"
            value={format.thousandsSeparator ?? ""}
            onChange={(event) =>
              update({ thousandsSeparator: event.target.value || null })
            }
          >
            <option value="">None</option>
            <option value=",">Comma</option>
            <option value=".">Dot</option>
            <option value=" ">Space</option>
            <option value=" ">Non-breaking space</option>
            <option value="'">Apostrophe</option>
          </select>
        </Field>
      </div>
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={format.stripCurrencySymbols}
          onChange={(event) =>
            update({ stripCurrencySymbols: event.target.checked })
          }
        />{" "}
        Remove surrounding currency symbols
      </label>
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={format.allowParentheses}
          onChange={(event) =>
            update({ allowParentheses: event.target.checked })
          }
        />{" "}
        Parentheses mean negative
      </label>
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={format.allowTrailingMinus}
          onChange={(event) =>
            update({ allowTrailingMinus: event.target.checked })
          }
        />{" "}
        Allow trailing minus
      </label>
    </>
  );
}

function ParsedPreview({ preview }: { preview: MappingPreview | null }) {
  if (!preview)
    return (
      <InlineNotice>
        Parsed preview appears after required fields are mapped.
      </InlineNotice>
    );
  return (
    <div
      className="preview-scroll"
      tabIndex={0}
      aria-label="Parsed transaction preview"
    >
      <table className="preview-table parsed">
        <thead>
          <tr>
            <th>Row</th>
            <th>Date</th>
            <th>Description</th>
            <th>Amount minor</th>
            <th>Currency</th>
            <th>Disposition</th>
            <th>Diagnostics</th>
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr
              key={row.rowNumber}
              className={row.errors.length ? "preview-error" : ""}
            >
              <th>{row.rowNumber}</th>
              <td>{row.transactionDate ?? row.transactionTimestamp ?? ""}</td>
              <td>{row.description ?? ""}</td>
              <td className="num">{row.amountMinor ?? ""}</td>
              <td>{row.currency ?? ""}</td>
              <td>{row.disposition}</td>
              <td>{row.errors.join("; ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PreviewPagination({
  offset,
  limit,
  total,
  shownEnd,
  onOffset,
  onLimit,
  label,
}: {
  offset: number;
  limit: number;
  total: number;
  shownEnd: number;
  onOffset: (offset: number) => void;
  onLimit: (limit: number) => void;
  label: string;
}) {
  return (
    <div className="pagination">
      <button
        className="button secondary"
        disabled={offset <= 0}
        onClick={() => onOffset(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span>
        {total
          ? `${offset + 1}-${shownEnd} of ${total} ${label}`
          : `No ${label}`}
      </span>
      <Field
        label="Rows per page"
        htmlFor={`${label.replaceAll(" ", "-")}-page-size`}
      >
        <select
          id={`${label.replaceAll(" ", "-")}-page-size`}
          value={limit}
          onChange={(event) => onLimit(Number(event.target.value))}
        >
          {previewPageSizes.map((size) => (
            <option key={size}>{size}</option>
          ))}
        </select>
      </Field>
      <button
        className="button secondary"
        disabled={offset + limit >= total}
        onClick={() => onOffset(offset + limit)}
      >
        Next
      </button>
    </div>
  );
}

function Diagnostics({
  diagnostics,
  title,
}: {
  diagnostics: ImportDiagnostic[];
  title: string;
}) {
  if (!diagnostics.length) return null;
  return (
    <section className="diagnostic-list" aria-live="polite">
      <h3>{title}</h3>
      {diagnostics.map((item, index) => (
        <InlineNotice
          key={`${item.code}-${item.rowNumber}-${index}`}
          tone={
            item.severity === "ERROR"
              ? "bad"
              : item.severity === "WARNING"
                ? "warn"
                : "neutral"
          }
        >
          <strong>{item.code}</strong>: {item.message}
          {item.field ? ` Field: ${item.field}.` : ""}
          {item.rowNumber ? ` Row: ${item.rowNumber}.` : ""}
        </InlineNotice>
      ))}
    </section>
  );
}

function StagingStep({ reload }: { reload: () => void }) {
  useEffect(() => {
    const timer = window.setInterval(reload, 2000);
    return () => window.clearInterval(timer);
  }, [reload]);
  return (
    <section className="ledger-panel panel-padding">
      <LoadingState label="Staging the full file into a recoverable review draft" />
      <InlineNotice>
        Staging is persisted. If the service restarts, reload this page to
        recover or retry the mapping.
      </InlineNotice>
      <button className="button secondary" onClick={reload}>
        Check status
      </button>
    </section>
  );
}

function RemapActions({ remap }: { remap: (step: "inspect" | "map") => void }) {
  return (
    <>
      <button
        className="button secondary"
        onClick={() => {
          if (
            window.confirm(
              "Changing inspection replaces staged rows and discards row-level review edits. Continue?",
            )
          )
            remap("inspect");
        }}
      >
        Change sheet or header
      </button>
      <button
        className="button secondary"
        onClick={() => {
          if (
            window.confirm(
              "Remapping replaces staged rows and discards row-level review edits. Continue?",
            )
          )
            remap("map");
        }}
      >
        Remap columns
      </button>
    </>
  );
}

function ReviewStep({
  batch,
  reload,
  onBatchChanged,
  remap,
}: {
  batch: ImportBatch;
  reload: () => void;
  onBatchChanged: (batch: ImportBatch) => void;
  remap: (step: "inspect" | "map") => void;
}) {
  return (
    <>
      <div className="review-stage-heading">
        <div>
          <h2>Review staged rows</h2>
          <p className="page-intro">
            Existing category, duplicate, validation, and serialized autosave
            behavior is unchanged.
          </p>
        </div>
        <div className="page-actions">
          <RemapActions remap={remap} />
          <button className="button" onClick={reload}>
            Check commit readiness
          </button>
        </div>
      </div>
      {batch.mappingRevision > 0 && (
        <InlineNotice tone="warn">
          This review uses mapping revision {batch.mappingRevision}. Remapping
          discards row-level edits.
        </InlineNotice>
      )}
      <ImportReviewPage embedded onBatchChanged={onBatchChanged} />
    </>
  );
}

function CommitStep({
  batch,
  committing,
  commit,
  remap,
}: {
  batch: ImportBatch;
  committing: boolean;
  commit: () => void;
  remap: (step: "inspect" | "map") => void;
}) {
  return (
    <section className="commit-panel ledger-panel panel-padding">
      <div>
        <p className="eyebrow">Ready for ledger</p>
        <h2>
          Commit {batch.includedRows} accepted{" "}
          {batch.includedRows === 1 ? "row" : "rows"}
        </h2>
        <p>
          This writes accepted rows atomically to the destination account.
          Backend staging counts are shown without inference.
        </p>
      </div>
      <dl className="commit-summary">
        <div>
          <dt>Accepted</dt>
          <dd>{batch.includedRows}</dd>
        </div>
        <div>
          <dt>Ignored</dt>
          <dd>{batch.ignoredRows}</dd>
        </div>
        <div>
          <dt>Audit only</dt>
          <dd>{batch.auditRows}</dd>
        </div>
        <div>
          <dt>Blocked</dt>
          <dd>{batch.blockedRows}</dd>
        </div>
        <div>
          <dt>Duplicate signals</dt>
          <dd>{batch.duplicateRows}</dd>
        </div>
        <div>
          <dt>Mapping revision</dt>
          <dd>{batch.mappingRevision}</dd>
        </div>
      </dl>
      <InlineNotice tone="good">
        All required review decisions are resolved. No ledger transaction has
        been written yet.
      </InlineNotice>
      <div className="form-actions">
        <button className="button" disabled={committing} onClick={commit}>
          {committing ? "Committing..." : "Commit accepted rows"}
        </button>
        <RemapActions remap={remap} />
      </div>
    </section>
  );
}
