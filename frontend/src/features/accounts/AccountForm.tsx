import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { Account } from "../../api/types";
import { Field, InlineNotice } from "../../components/ui";
import { isIso4217Currency } from "../../shared/currencies";

export function AccountForm({ onCreated, submitLabel = "Create account" }: { onCreated: (account: Account) => void; submitLabel?: string }) {
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currencyError = isIso4217Currency(currency) ? null : "Enter a valid ISO 4217 currency code.";

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || currencyError) return;
    setSaving(true);
    setError(null);
    try {
      const account = await api.accounts.create({ name: name.trim(), defaultCurrency: currency });
      setName("");
      setCurrency("EUR");
      onCreated(account);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The account could not be created.");
    } finally {
      setSaving(false);
    }
  }

  return <form onSubmit={create}>
    <div className="form-grid">
      <Field label="Account name" htmlFor="new-account-name"><input id="new-account-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} placeholder="Everyday account" /></Field>
      <Field label="Default currency" htmlFor="new-account-currency" error={currencyError}>{(accessibility) => <input {...accessibility} id="new-account-currency" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} placeholder="EUR" />}</Field>
    </div>
    {error && <InlineNotice tone="bad">{error}</InlineNotice>}
    <div className="form-actions"><button className="button" disabled={saving || !name.trim() || Boolean(currencyError)}>{saving ? "Creating..." : submitLabel}</button></div>
  </form>;
}
