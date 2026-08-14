import { useState, type FormEvent } from "react";
import { BrainCircuit, Pencil, Power, Plus, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { Category, Subcategory, TaggingModel } from "../api/types";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { useResource } from "../hooks/use-resource";
import { categoryName, subcategoriesFor, subcategoryName, taxonomyError } from "../shared/taxonomy";

export default function CategoriesPage() {
  const [tab, setTab] = useState<"taxonomy" | "model">("taxonomy");
  const categories = useResource(() => api.taxonomy.categories(), "managed-categories");
  const accounts = useResource(() => api.accounts.list(), "rule-accounts");
  const rules = useResource(() => api.tagRules.list(), "tag-rules");
  const [categoryDraft, setCategoryDraft] = useState("");
  const [subcategoryDraft, setSubcategoryDraft] = useState({ categoryId: "", name: "" });
  const [editing, setEditing] = useState<{ type: "category" | "subcategory"; id: string; name: string } | null>(null);
  const [ruleDraft, setRuleDraft] = useState({ match: "", scope: "GLOBAL", accountId: "", categoryId: "", subcategoryId: "" });
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const taxonomy = categories.data ?? [];
  const ruleError = taxonomyError(taxonomy, ruleDraft.categoryId || null, ruleDraft.subcategoryId || null);

  async function perform(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ tone: "good", text: success });
      categories.reload();
      rules.reload();
      return true;
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : "The taxonomy change could not be saved." });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addCategory(event: FormEvent) {
    event.preventDefault();
    const name = categoryDraft.trim();
    if (!name) return;
    if (await perform(() => api.taxonomy.createCategory(name), `Added "${name}".`)) setCategoryDraft("");
  }

  async function addSubcategory(event: FormEvent) {
    event.preventDefault();
    const name = subcategoryDraft.name.trim();
    if (!subcategoryDraft.categoryId || !name) return;
    if (await perform(() => api.taxonomy.createSubcategory(subcategoryDraft.categoryId, name), `Added "${name}".`)) setSubcategoryDraft((current) => ({ ...current, name: "" }));
  }

  async function saveRename() {
    if (!editing?.name.trim()) return;
    const action = editing.type === "category"
      ? () => api.taxonomy.patchCategory(editing.id, { name: editing.name.trim() })
      : () => api.taxonomy.patchSubcategory(editing.id, { name: editing.name.trim() });
    if (await perform(action, "Name updated.")) setEditing(null);
  }

  function toggleCategory(category: Category) {
    if (category.active && !window.confirm(`Deactivate "${category.name}"? Existing ledger labels remain, but new selections cannot use it.`)) return;
    void perform(() => api.taxonomy.patchCategory(category.id, { active: !category.active }), `${category.name} is now ${category.active ? "inactive" : "active"}.`);
  }

  function toggleSubcategory(subcategory: Subcategory) {
    if (subcategory.active && !window.confirm(`Deactivate "${subcategory.name}"? Existing ledger labels remain unchanged.`)) return;
    void perform(() => api.taxonomy.patchSubcategory(subcategory.id, { active: !subcategory.active }), `${subcategory.name} is now ${subcategory.active ? "inactive" : "active"}.`);
  }

  async function addRule(event: FormEvent) {
    event.preventDefault();
    if (!ruleDraft.match.trim() || !ruleDraft.categoryId || ruleError) return;
    if (await perform(() => api.tagRules.create({
      match: ruleDraft.match.trim(),
      scope: ruleDraft.scope,
      accountId: ruleDraft.scope === "ACCOUNT" ? ruleDraft.accountId : null,
      categoryId: ruleDraft.categoryId,
      subcategoryId: ruleDraft.subcategoryId || null,
    }), "Exact-match rule added.")) setRuleDraft({ match: "", scope: "GLOBAL", accountId: "", categoryId: "", subcategoryId: "" });
  }

  return (
    <>
      <PageHeader eyebrow="Managed taxonomy" title="Categories" description="Maintain the parent-constrained classification used by imports and corrections. Deactivation preserves history; it only closes the label to future choices." />
      <div className="tabs" aria-label="Category management mode">
        <button type="button" className="tab-button" aria-pressed={tab === "taxonomy"} onClick={() => setTab("taxonomy")}>Taxonomy &amp; rules</button>
        <button type="button" className="tab-button" aria-pressed={tab === "model"} onClick={() => setTab("model")}><BrainCircuit aria-hidden="true" /> Model training</button>
      </div>
      {tab === "taxonomy" ? <>
      {message && <InlineNotice tone={message.tone}>{message.text}</InlineNotice>}
      <div className="two-column" style={{ marginTop: "1.5rem" }}>
        <section>
          <div className="section-heading"><h2>Hierarchy</h2><p>Parent then subcategory</p></div>
          {categories.loading ? <LoadingState label="Loading category hierarchy" /> : categories.error ? <ErrorState error={categories.error} retry={categories.reload} /> : !taxonomy.length ? <EmptyState title="No categories" description="Add the first parent category to establish the ledger taxonomy." /> : (
            <div className="hierarchy">
              {taxonomy.map((category) => (
                <section className={`category-group ${category.active ? "" : "inactive"}`} key={category.id}>
                  <div className="category-row">
                    {editing?.type === "category" && editing.id === category.id ? <input aria-label={`Rename ${category.name}`} value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /> : <div><h3>{category.name}</h3><StatusBadge tone={category.active ? "good" : "neutral"}>{category.active ? "Active" : "Inactive"}</StatusBadge></div>}
                     {editing?.type === "category" && editing.id === category.id ? <button className="button" onClick={() => void saveRename()}>Save name</button> : <button className="button secondary" onClick={() => setEditing({ type: "category", id: category.id, name: category.name })}><Pencil aria-hidden="true" /> Rename</button>}
                    <button className="icon-button" aria-label={`${category.active ? "Deactivate" : "Activate"} ${category.name}`} onClick={() => toggleCategory(category)}><Power aria-hidden="true" /></button>
                  </div>
                  {category.subcategories.map((subcategory) => (
                    <div className={`subcategory-row ${subcategory.active ? "" : "inactive"}`} key={subcategory.id}>
                      {editing?.type === "subcategory" && editing.id === subcategory.id ? <input aria-label={`Rename ${subcategory.name}`} value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /> : <span>{subcategory.name}</span>}
                       {editing?.type === "subcategory" && editing.id === subcategory.id ? <button className="button" onClick={() => void saveRename()}>Save name</button> : <button className="button ghost" onClick={() => setEditing({ type: "subcategory", id: subcategory.id, name: subcategory.name })}><Pencil aria-hidden="true" /> Rename</button>}
                      <button className="icon-button" aria-label={`${subcategory.active ? "Deactivate" : "Activate"} ${subcategory.name}`} onClick={() => toggleSubcategory(subcategory)}><Power aria-hidden="true" /></button>
                    </div>
                  ))}
                </section>
              ))}
            </div>
          )}
        </section>
        <aside>
          <section className="ledger-panel panel-padding">
            <h2>Add labels</h2>
            <form onSubmit={addCategory}>
              <Field label="New parent category" htmlFor="new-category"><input id="new-category" value={categoryDraft} onChange={(event) => setCategoryDraft(event.target.value)} placeholder="e.g. Household" /></Field>
              <div className="form-actions"><button className="button" disabled={busy || !categoryDraft.trim()}><Plus aria-hidden="true" /> Add category</button></div>
            </form>
            <hr style={{ margin: "1.5rem 0", border: 0, borderTop: "1px solid var(--rule)" }} />
            <form onSubmit={addSubcategory} className="form-grid">
              <Field label="Parent" htmlFor="subcategory-parent"><select id="subcategory-parent" value={subcategoryDraft.categoryId} onChange={(event) => setSubcategoryDraft((current) => ({ ...current, categoryId: event.target.value }))}><option value="">Choose category</option>{taxonomy.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="New subcategory" htmlFor="new-subcategory"><input id="new-subcategory" value={subcategoryDraft.name} onChange={(event) => setSubcategoryDraft((current) => ({ ...current, name: event.target.value }))} placeholder="e.g. Utilities" /></Field>
              <div className="form-actions wide"><button className="button secondary" disabled={busy || !subcategoryDraft.categoryId || !subcategoryDraft.name.trim()}><Plus aria-hidden="true" /> Add subcategory</button></div>
            </form>
          </section>
        </aside>
      </div>

      <section style={{ marginTop: "3rem" }}>
        <div className="section-heading"><h2>Exact-match rules</h2><p>Applied before model predictions</p></div>
         <form className="filter-bar" onSubmit={addRule}>
           <Field label="Normalized description" htmlFor="rule-match"><input id="rule-match" value={ruleDraft.match} onChange={(event) => setRuleDraft((current) => ({ ...current, match: event.target.value }))} placeholder="exact merchant description" /></Field>
            <Field label="Scope" htmlFor="rule-scope"><select id="rule-scope" value={ruleDraft.scope} onChange={(event) => setRuleDraft((current) => ({ ...current, scope: event.target.value, accountId: "" }))}><option value="GLOBAL">Global</option><option value="ACCOUNT">Account</option></select></Field>
            {ruleDraft.scope === "ACCOUNT" && <Field label="Account" htmlFor="rule-account"><select id="rule-account" value={ruleDraft.accountId} onChange={(event) => setRuleDraft((current) => ({ ...current, accountId: event.target.value }))}><option value="">Choose account</option>{accounts.data?.map((account) => <option value={account.id} key={account.id}>{account.name}</option>)}</select></Field>}
          <Field label="Category" htmlFor="rule-category"><select id="rule-category" value={ruleDraft.categoryId} onChange={(event) => setRuleDraft({ ...ruleDraft, categoryId: event.target.value, subcategoryId: "" })}><option value="">Choose category</option>{taxonomy.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
           <Field label="Subcategory" htmlFor="rule-subcategory" error={ruleError}>{(accessibility) => <select {...accessibility} id="rule-subcategory" disabled={!ruleDraft.categoryId} value={ruleDraft.subcategoryId} onChange={(event) => setRuleDraft((current) => ({ ...current, subcategoryId: event.target.value }))}><option value="">None</option>{subcategoriesFor(taxonomy, ruleDraft.categoryId || null).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}</Field>
            <div className="form-actions"><button className="button" disabled={busy || !ruleDraft.match.trim() || !ruleDraft.categoryId || (ruleDraft.scope === "ACCOUNT" && !ruleDraft.accountId) || Boolean(ruleError)}>Add exact rule</button></div>
        </form>
        {rules.loading ? <LoadingState label="Loading exact-match rules" /> : rules.error ? <ErrorState error={rules.error} retry={rules.reload} /> : rules.data?.length ? rules.data.map((rule) => (
            <div className={`rule-row ${rule.active ? "" : "inactive"}`} key={rule.id}><strong>"{rule.match}"</strong><span>{categoryName(taxonomy, rule.categoryId)} / {subcategoryName(taxonomy, rule.subcategoryId)}</span><span>{rule.accountId ? accounts.data?.find((account) => account.id === rule.accountId)?.name ?? "Account" : "Global"}</span><button className="button ghost" disabled={busy} onClick={() => void perform(() => api.tagRules.patch(rule.id, { active: !rule.active }), `Rule ${rule.active ? "disabled" : "enabled"}.`)}><Power aria-hidden="true" /> {rule.active ? "Disable" : "Enable"}</button></div>
        )) : <EmptyState title="No exact-match rules" description="Rules appear only after an explicit correction is remembered or a rule is added here." />}
      </section>
      </> : <ModelTrainingPanel />}
    </>
  );
}

function ModelTrainingPanel() {
  const models = useResource(() => api.taggingModels.overview(), "tagging-model-overview");
  const [busy, setBusy] = useState<"retrain" | "activate" | "reject" | "restore" | null>(null);
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const active = models.data?.active ?? null;
  const candidate = models.data?.candidate ?? null;
  const previous = models.data?.previous ?? null;
  const settingsModel = candidate ?? active;

  async function retrain() {
    setBusy("retrain");
    setMessage(null);
    try {
      await api.taggingModels.retrain();
      setMessage({ tone: "good", text: "Candidate trained. Compare its results before activation." });
      models.reload();
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : "The model could not be retrained." });
    } finally {
      setBusy(null);
    }
  }

  async function activate(model: TaggingModel, restoring = false) {
    const delta = exactMatchDelta(model, active);
    if (!restoring && delta != null && delta < 0 && !window.confirm("This candidate has lower exact-match accuracy. Activate it anyway?")) return;
    if (restoring && !window.confirm("Restore the previous model as active?")) return;
    setBusy(restoring ? "restore" : "activate");
    setMessage(null);
    try {
      await api.taggingModels.activate(model.modelVersionId);
      setMessage({ tone: "good", text: restoring ? "Previous model restored." : "Candidate activated. The replaced model is available for rollback." });
      models.reload();
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : "The model could not be activated." });
    } finally {
      setBusy(null);
    }
  }

  async function reject() {
    if (!candidate || !window.confirm("Reject and permanently delete this candidate?")) return;
    setBusy("reject");
    setMessage(null);
    try {
      await api.taggingModels.reject(candidate.modelVersionId);
      setMessage({ tone: "good", text: "Candidate rejected. The active model was not changed." });
      models.reload();
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : "The candidate could not be rejected." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="model-training">
      <div className="ledger-panel panel-padding model-training-intro">
        <div>
          <p className="eyebrow">Active classifier</p>
          <h2>Train from the full labeled ledger</h2>
          <p>Retraining creates one reviewable candidate. The active model changes only after explicit activation, and one previous version remains available for rollback.</p>
        </div>
        <button className="button" type="button" disabled={busy !== null || candidate !== null} onClick={() => void retrain()}>
          <RefreshCw className={busy === "retrain" ? "spin" : ""} aria-hidden="true" />
          {busy === "retrain" ? "Training candidate..." : candidate ? "Candidate awaiting review" : "Train candidate"}
        </button>
      </div>

      <dl className="model-settings" aria-label="Model training settings">
        <div><dt>Category threshold</dt><dd>{percent(settingsModel?.categoryThreshold ?? 0.7)}</dd></div>
        <div><dt>Subcategory threshold</dt><dd>{percent(settingsModel?.subcategoryThreshold ?? 0.8)}</dd></div>
        <div><dt>Validation</dt><dd>{settingsModel?.crossValidation?.requestedFolds ?? 5} grouped folds</dd></div>
        <div><dt>Training data</dt><dd>All eligible labels</dd></div>
      </dl>

      {message && <InlineNotice tone={message.tone}>{message.text}</InlineNotice>}
      {models.loading ? <LoadingState label="Loading model versions" /> : models.error ? <ErrorState error={models.error} retry={models.reload} /> : <>
        {candidate ? <CandidateComparison active={active} candidate={candidate} busy={busy} activate={() => void activate(candidate)} reject={() => void reject()} /> : active ? <ActiveModelSummary model={active} /> : <EmptyState title="No active model" description="Train a candidate after every represented category has at least two distinct labeled descriptions." />}
        {previous && <section className="ledger-panel panel-padding model-previous">
          <div><StatusBadge tone="warn">Previous</StatusBadge><h3>{previous.modelName}</h3><p>Activated {formatModelDate(previous.activatedAt)} · Exact hierarchy match {metricPercent(previous.crossValidation?.exactMatchAccuracy)}</p></div>
          <button className="button secondary" type="button" disabled={busy !== null || candidate !== null || !previous.taxonomyCurrent} onClick={() => void activate(previous, true)}>{busy === "restore" ? "Restoring..." : "Restore previous"}</button>
        </section>}
      </>}
    </section>
  );
}

function CandidateComparison({ active, candidate, busy, activate, reject }: { active: TaggingModel | null; candidate: TaggingModel; busy: string | null; activate: () => void; reject: () => void }) {
  const delta = exactMatchDelta(candidate, active);
  const comparable = active?.evaluationSchemaVersion === candidate.evaluationSchemaVersion;
  const sameSnapshot = Boolean(active?.trainingDataChecksum && active.trainingDataChecksum === candidate.trainingDataChecksum);
  return <section className="model-candidate ledger-panel panel-padding">
    <header className="model-candidate-header"><div><StatusBadge tone="warn">Candidate</StatusBadge><h2>{candidateHeadline(delta)}</h2><p>Trained {formatModelDate(candidate.createdAt)} from {candidate.trainingRowCount.toLocaleString()} labeled rows.</p></div><div className="page-actions"><button className="button secondary" type="button" disabled={busy !== null} onClick={reject}>{busy === "reject" ? "Rejecting..." : "Reject"}</button><button className="button" type="button" disabled={busy !== null || !candidate.taxonomyCurrent} onClick={activate}>{busy === "activate" ? "Activating..." : "Activate candidate"}</button></div></header>
    {!candidate.taxonomyCurrent && <InlineNotice tone="bad">The taxonomy changed after training. Reject this candidate and train another.</InlineNotice>}
    {!comparable && active && <InlineNotice tone="warn">The evaluation method differs from the active model, so improvement deltas are unavailable.</InlineNotice>}
    {comparable && active && !sameSnapshot && <InlineNotice tone="warn">These runs used different ledger snapshots. Deltas are advisory, not a promotion guarantee.</InlineNotice>}
    <div className="model-comparison-scroll"><table className="data-table model-comparison-table"><thead><tr><th>Metric</th><th>Active</th><th>Candidate</th><th>Change</th></tr></thead><tbody>
      <ComparisonRow label="Exact hierarchy match" active={active?.crossValidation?.exactMatchAccuracy} candidate={candidate.crossValidation?.exactMatchAccuracy} comparable={comparable} primary />
      <ComparisonRow label="Category accuracy" active={active?.crossValidation?.categoryAccuracy} candidate={candidate.crossValidation?.categoryAccuracy} comparable={comparable} />
      <ComparisonRow label="Auto-accept accuracy" active={active?.crossValidation?.autoAcceptAccuracy} candidate={candidate.crossValidation?.autoAcceptAccuracy} comparable={comparable} />
      <ComparisonRow label="Auto-accept coverage" active={active?.crossValidation?.autoAcceptCoverage} candidate={candidate.crossValidation?.autoAcceptCoverage} comparable={comparable} />
    </tbody></table></div>
    <dl className="model-meta"><div><dt>Active rows</dt><dd>{active?.trainingRowCount.toLocaleString() ?? "No baseline"}</dd></div><div><dt>Candidate rows</dt><dd>{candidate.trainingRowCount.toLocaleString()}</dd></div><div><dt>Active folds</dt><dd>{active?.crossValidation?.effectiveFolds ?? "Not recorded"}</dd></div><div><dt>Candidate folds</dt><dd>{candidate.crossValidation?.effectiveFolds ?? "Not recorded"}</dd></div></dl>
  </section>;
}

function ActiveModelSummary({ model }: { model: TaggingModel }) {
  return <section><div className="section-heading model-result-heading"><h2>Active cross-validation results</h2><p>Activated {formatModelDate(model.activatedAt)}</p></div>{model.crossValidation ? <div className="metric-strip model-metrics"><ModelMetric label="Category accuracy" value={percent(model.crossValidation.categoryAccuracy)} /><ModelMetric label="Exact hierarchy match" value={percent(model.crossValidation.exactMatchAccuracy)} /><ModelMetric label="Auto-accept coverage" value={percent(model.crossValidation.autoAcceptCoverage)} /><ModelMetric label="Auto-accept accuracy" value={metricPercent(model.crossValidation.autoAcceptAccuracy)} /></div> : <EmptyState title="No validation metrics" description="This model predates cross-validation. Train a candidate to measure current performance." />}<dl className="model-meta"><div><dt>Training rows</dt><dd>{model.trainingRowCount.toLocaleString()}</dd></div><div><dt>Categories</dt><dd>{model.categoryCount}</dd></div><div><dt>Effective folds</dt><dd>{model.crossValidation ? `${model.crossValidation.effectiveFolds} of ${model.crossValidation.requestedFolds}` : "Not recorded"}</dd></div><div><dt>Evaluated rows</dt><dd>{model.crossValidation?.evaluatedRowCount.toLocaleString() ?? "Not recorded"}</dd></div></dl></section>;
}

function ComparisonRow({ label, active, candidate, comparable, primary = false }: { label: string; active: number | null | undefined; candidate: number | null | undefined; comparable: boolean; primary?: boolean }) {
  const delta = active == null || candidate == null || !comparable ? null : candidate - active;
  return <tr className={primary ? "primary-comparison" : ""}><th scope="row">{label}</th><td>{metricPercent(active)}</td><td>{metricPercent(candidate)}</td><td className={delta == null ? "" : delta >= 0 ? "positive-delta" : "negative-delta"}>{delta == null ? "N/A" : percentagePointDelta(delta)}</td></tr>;
}

function ModelMetric({ label, value }: { label: string; value: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong></article>;
}

function percent(value: number): string {
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function metricPercent(value: number | null | undefined): string {
  return value == null ? "N/A" : percent(value);
}

function exactMatchDelta(candidate: TaggingModel, active: TaggingModel | null): number | null {
  if (!active || active.evaluationSchemaVersion !== candidate.evaluationSchemaVersion) return null;
  const activeValue = active.crossValidation?.exactMatchAccuracy;
  const candidateValue = candidate.crossValidation?.exactMatchAccuracy;
  return activeValue == null || candidateValue == null ? null : candidateValue - activeValue;
}

function candidateHeadline(delta: number | null): string {
  if (delta == null) return "Candidate ready for review";
  if (Math.abs(delta) < 0.0005) return "Exact-match accuracy is unchanged";
  return `Exact-match accuracy is ${absolutePercentagePoints(delta)} ${delta > 0 ? "better" : "worse"}`;
}

function percentagePointDelta(value: number): string {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, signDisplay: "always" }).format(value * 100);
  return `${formatted} pp`;
}

function absolutePercentagePoints(value: number): string {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Math.abs(value) * 100);
  return `${formatted} pp`;
}

function formatModelDate(value: string | null): string {
  if (!value) return "at an unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "at an unknown time" : date.toLocaleString();
}
