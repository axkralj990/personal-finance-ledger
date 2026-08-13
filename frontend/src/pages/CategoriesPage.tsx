import { useState, type FormEvent } from "react";
import { Pencil, Power, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Category, Subcategory } from "../api/types";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { useResource } from "../hooks/use-resource";
import { categoryName, subcategoriesFor, subcategoryName, taxonomyError } from "../shared/taxonomy";

export default function CategoriesPage() {
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
    </>
  );
}
