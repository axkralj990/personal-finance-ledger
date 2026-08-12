import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle, RotateCcw } from "lucide-react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 data-page-heading tabIndex={-1}>{title}</h1>
        <p className="page-intro">{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function LoadingState({ label = "Loading ledger data" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="state-panel state-error" role="alert">
      <AlertCircle aria-hidden="true" />
      <div>
        <strong>Ledger data unavailable</strong>
        <p>{error.message}</p>
      </div>
      {retry && <button className="button secondary" onClick={retry}><RotateCcw aria-hidden="true" /> Retry</button>}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="state-panel empty-state">
      <Inbox aria-hidden="true" />
      <div><strong>{title}</strong><p>{description}</p></div>
      {action}
    </div>
  );
}

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

interface FieldControlProps {
  "aria-invalid"?: true;
  "aria-describedby"?: string;
}

export function Field({ label, htmlFor, hint, error, children }: { label: string; htmlFor: string; hint?: string; error?: string | null; children: ReactNode | ((props: FieldControlProps) => ReactNode) }) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const controlProps: FieldControlProps = {
    ...(error && { "aria-invalid": true }),
    ...(describedBy && { "aria-describedby": describedBy }),
  };
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {typeof children === "function" ? children(controlProps) : children}
      {hint && <p id={hintId} className="field-hint">{hint}</p>}
      {error && <p id={errorId} className="field-error" role="alert">{error}</p>}
    </div>
  );
}

export function InlineNotice({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  return <div className={`notice notice-${tone}`} role={tone === "bad" ? "alert" : "status"}>{children}</div>;
}
