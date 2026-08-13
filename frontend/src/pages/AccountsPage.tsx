import { useState } from "react";
import { Pencil, Power, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Account } from "../api/types";
import { EmptyState, ErrorState, Field, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { AccountForm } from "../features/accounts/AccountForm";
import { useResource } from "../hooks/use-resource";

export default function AccountsPage() {
  const accounts = useResource(() => api.accounts.list(), "managed-accounts");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  async function rename(account: Account) {
    const name = editing?.id === account.id ? editing.name.trim() : "";
    if (!name) return;
    setBusyId(account.id);
    setMessage(null);
    try {
      await api.accounts.patch(account.id, { name });
      setEditing(null);
      setMessage({ tone: "good", text: `Renamed account to "${name}".` });
      accounts.reload();
    } catch (caught) {
      setMessage({ tone: "bad", text: caught instanceof Error ? caught.message : "The account could not be renamed." });
    } finally {
      setBusyId(null);
    }
  }

  async function toggle(account: Account) {
    if (account.active && !window.confirm(`Deactivate "${account.name}"? Existing transactions keep this account, but it will no longer be available for new imports.`)) return;
    setBusyId(account.id);
    setMessage(null);
    try {
      await api.accounts.patch(account.id, { active: !account.active });
      setMessage({ tone: "good", text: `${account.name} is now ${account.active ? "inactive" : "active"}.` });
      accounts.reload();
    } catch (caught) {
      setMessage({ tone: "bad", text: caught instanceof Error ? caught.message : "The account status could not be changed." });
    } finally {
      setBusyId(null);
    }
  }

  return <>
    <PageHeader eyebrow="Ledger destinations" title="Accounts" description="Name the places where transactions belong. Deactivation removes an account from new imports while preserving its complete ledger history." actions={<button className="button" onClick={() => setCreating((value) => !value)}><Plus aria-hidden="true" /> {creating ? "Close form" : "Create account"}</button>} />
    {message && <InlineNotice tone={message.tone}>{message.text}</InlineNotice>}
    {creating && <section className="ledger-panel panel-padding account-create-panel"><div className="section-heading"><h2>New account</h2><p>Generic ledger account</p></div><AccountForm onCreated={(account) => { setCreating(false); setMessage({ tone: "good", text: `Created "${account.name}".` }); accounts.reload(); }} /></section>}
    <section className="account-directory" aria-labelledby="account-directory-title">
      <div className="section-heading"><h2 id="account-directory-title">Account directory</h2><p>{accounts.data?.length ?? 0} total</p></div>
      {accounts.loading ? <LoadingState label="Loading accounts" /> : accounts.error ? <ErrorState error={accounts.error} retry={accounts.reload} /> : !accounts.data?.length ? <EmptyState title="No accounts" description="Create the first account to start importing transactions." /> : accounts.data.map((account) => <article className={`account-row ${account.active ? "" : "inactive"}`} key={account.id}>
        <div className="account-row-name">{editing?.id === account.id ? <Field label={`Rename ${account.name}`} htmlFor={`rename-${account.id}`}><input id={`rename-${account.id}`} value={editing.name} onChange={(event) => setEditing({ id: account.id, name: event.target.value })} /></Field> : <><h3>{account.name}</h3><span>{account.defaultCurrency} default currency</span></>}</div>
        <StatusBadge tone={account.active ? "good" : "neutral"}>{account.active ? "Active" : "Inactive"}</StatusBadge>
        <div className="account-row-actions">{editing?.id === account.id ? <><button className="button" disabled={busyId === account.id || !editing.name.trim()} onClick={() => void rename(account)}>Save name</button><button className="button ghost" onClick={() => setEditing(null)}>Cancel</button></> : <button className="button secondary" onClick={() => setEditing({ id: account.id, name: account.name })}><Pencil aria-hidden="true" /> Rename</button>}<button className="button ghost" disabled={busyId === account.id} onClick={() => void toggle(account)}><Power aria-hidden="true" /> {account.active ? "Deactivate" : "Reactivate"}</button></div>
      </article>)}
    </section>
  </>;
}
