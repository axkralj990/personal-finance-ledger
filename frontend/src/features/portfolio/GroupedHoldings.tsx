import { Fragment, useState } from "react";
import { CalendarPlus, ChevronRight, Pencil, Plus } from "lucide-react";
import type { Asset, PortfolioHolding } from "../../api/types";
import { StatusBadge } from "../../components/ui";
import { formatDate, formatMoney } from "../../shared/format";
import type { HoldingGroup } from "./grouping";

const EUR = "EUR";
const DAY_MS = 86_400_000;
const TYPE_LABELS: Record<PortfolioHolding["assetType"], string> = { BANK_CASH: "Bank cash", BROKERAGE_CASH: "Brokerage cash", ETF: "ETF", STOCK: "Stock", FIXED_ASSET: "Fixed asset", OTHER: "Other" };

function percent(value: string | null): string { return value == null ? "Unavailable" : `${value}%`; }
function pnlClass(value: number | null): string { return value == null ? "" : value >= 0 ? "portfolio-positive" : "portfolio-negative"; }
function valuationSourceLabel(source: PortfolioHolding["source"]): string { return source === "TWELVE_DATA" ? "Twelve Data" : source === "YAHOO_FINANCE" ? "Yahoo Finance" : "Manual"; }
function staleQuote(holding: PortfolioHolding, asOf: string): boolean {
  if (holding.source === "MANUAL" || !holding.source || !holding.valuedAt) return false;
  return (Date.parse(`${asOf}T00:00:00Z`) - Date.parse(`${holding.valuedAt}T00:00:00Z`)) / DAY_MS > 3;
}

function HoldingActions({ asset, onEdit, onValue }: { asset: Asset | undefined; onEdit: () => void; onValue: () => void }) {
  return <div className="holding-actions"><button className="button ghost" type="button" disabled={!asset} onClick={onValue}><CalendarPlus aria-hidden="true" /> Add valuation</button><button className="icon-button" type="button" disabled={!asset} aria-label={`Edit ${asset?.name ?? "asset"}`} onClick={onEdit}><Pencil aria-hidden="true" /></button></div>;
}

function ValuationEvidence({ holding, asOf }: { holding: PortfolioHolding; asOf: string }) {
  if (!holding.source) return <>No source</>;
  const stale = staleQuote(holding, asOf);
  const marketSource = holding.source === "TWELVE_DATA" ? "Twelve Data" : holding.source === "YAHOO_FINANCE" ? "Yahoo Finance" : null;
  return <>{marketSource && <StatusBadge tone={stale ? "warn" : "good"}>{stale ? "Stale quote" : marketSource}</StatusBadge>}{holding.source === "MANUAL" && <StatusBadge>Manual</StatusBadge>}<small>{formatDate(holding.valuedAt)}</small></>;
}

function GroupEvidence({ group, asOf }: { group: HoldingGroup; asOf: string }) {
  if (!group.valuedCount) return <>No source</>;
  if (group.mixedEvidence) return <><StatusBadge tone="warn">Mixed evidence</StatusBadge><small>Oldest {formatDate(group.valuedAt)}</small></>;
  const representative = group.lots.find((lot) => lot.holding.valuedAt === group.valuedAt)?.holding ?? group.lots[0]!.holding;
  return <ValuationEvidence holding={representative} asOf={asOf} />;
}

export function GroupedHoldings({ groups, asOf, onAddPurchase, onEdit, onValue }: { groups: HoldingGroup[]; asOf: string; onAddPurchase: (assets: Asset[]) => void; onEdit: (asset: Asset) => void; onValue: (asset: Asset) => void }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) => setExpanded((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  return <section className="portfolio-holdings" aria-labelledby="holdings-title"><header><div><p className="eyebrow">Active book</p><h2 id="holdings-title">Holdings and latest evidence</h2></div><p>{groups.filter((group) => !group.missingValuation).length} valued / {groups.length} positions</p></header>
    <div className="desktop-table portfolio-table-scroll"><table className="data-table"><caption className="sr-only">Active portfolio positions with expandable purchase lots</caption><thead><tr><th>Holding</th><th>Position</th><th className="amount">Latest value</th><th className="amount">Cost basis</th><th className="amount">Unrealized P&amp;L</th><th>Valuation</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{groups.map((group) => {
      const isExpanded = expanded.has(group.key);
      const groupAssets = group.lots.flatMap((lot) => lot.asset ? [lot.asset] : []);
      const template = groupAssets[0];
      const singleton = group.lots.length === 1 ? template : undefined;
      const tracksPnl = group.assetType !== "BANK_CASH" && group.assetType !== "BROKERAGE_CASH";
      const venue = group.exchange ?? group.micCode;
      return <Fragment key={group.key}><tr className={group.missingValuation ? "holding-missing" : ""}><td>{group.lots.length > 1 ? <button className="holding-disclosure" type="button" aria-expanded={isExpanded} aria-controls={`lots-${group.key}`} onClick={() => toggle(group.key)}><ChevronRight aria-hidden="true" /><span><strong>{group.name}</strong><small>{TYPE_LABELS[group.assetType]} / {group.currency}{venue ? ` / ${venue}` : ""} / {group.lots.length} purchases</small></span></button> : <><strong>{group.name}</strong><small>{TYPE_LABELS[group.assetType]} / {group.currency}{venue ? ` / ${venue}` : ""}</small></>}</td><td>{group.quantity ?? "Not quantity-based"}</td><td className="amount">{!group.valuedCount ? <StatusBadge tone="warn">Missing valuation</StatusBadge> : <><strong>{formatMoney(group.eurValueMinor, EUR)}</strong>{group.currency !== EUR && <small>{formatMoney(group.nativeValueMinor, group.currency)}</small>}{group.missingValuation && <small>{group.valuedCount} of {group.lots.length} purchases valued</small>}</>}</td><td className="amount">{formatMoney(group.costBasisEurMinor, EUR)}</td><td className={`amount ${pnlClass(group.unrealizedPnlMinor)}`}>{formatMoney(group.unrealizedPnlMinor, EUR)}<small>{percent(group.returnPercent)}</small>{tracksPnl && group.pnlCoveredCount < group.lots.length && <small>{group.pnlCoveredCount} of {group.lots.length} purchases covered</small>}</td><td><GroupEvidence group={group} asOf={asOf} /></td><td><div className="holding-actions">{group.isSecurity && template && <button className="button ghost" type="button" aria-label={`Add ${group.symbol ?? group.name}${venue ? ` on ${venue}` : ""} purchase`} onClick={() => onAddPurchase(groupAssets)}><Plus aria-hidden="true" /> Add purchase</button>}{singleton && <HoldingActions asset={singleton} onValue={() => onValue(singleton)} onEdit={() => onEdit(singleton)} />}</div></td></tr>
        {group.lots.length > 1 && isExpanded && group.lots.map(({ asset, holding }, index) => <tr className="holding-lot-row" id={index === 0 ? `lots-${group.key}` : undefined} key={holding.assetId}><td><strong>Purchased {formatDate(asset?.acquisitionDate)}</strong><small>{asset?.quote?.symbol ?? holding.name} lot</small></td><td>{holding.quantity ?? "Not quantity-based"}</td><td className="amount">{holding.missingValuation ? <StatusBadge tone="warn">Missing valuation</StatusBadge> : <><strong>{formatMoney(holding.eurValueMinor, EUR)}</strong>{holding.currency !== EUR && <small>{formatMoney(holding.nativeValueMinor, holding.currency)}</small>}</>}</td><td className="amount">{formatMoney(holding.costBasisEurMinor, EUR)}</td><td className={`amount ${pnlClass(holding.unrealizedPnlMinor)}`}>{formatMoney(holding.unrealizedPnlMinor, EUR)}<small>{percent(holding.returnPercent)}</small></td><td><ValuationEvidence holding={holding} asOf={asOf} /></td><td><HoldingActions asset={asset} onValue={() => asset && onValue(asset)} onEdit={() => asset && onEdit(asset)} /></td></tr>)}</Fragment>;
    })}</tbody></table></div>
    <div className="mobile-records">{groups.map((group) => {
      const isExpanded = expanded.has(group.key);
      const groupAssets = group.lots.flatMap((lot) => lot.asset ? [lot.asset] : []);
      const template = groupAssets[0];
      const singleton = group.lots.length === 1 ? template : undefined;
      const venue = group.exchange ?? group.micCode;
      return <article className={`portfolio-holding-card ${group.missingValuation ? "holding-missing" : ""}`} key={group.key}><header><div><h3>{group.name}</h3><p>{TYPE_LABELS[group.assetType]} / {group.currency}{venue ? ` / ${venue}` : ""}{group.quantity ? ` / ${group.quantity} units` : ""}{group.lots.length > 1 ? ` / ${group.lots.length} purchases` : ""}</p></div>{!group.valuedCount ? <StatusBadge tone="warn">Missing value</StatusBadge> : <strong className="amount">{formatMoney(group.eurValueMinor, EUR)}</strong>}</header><dl><div><dt>Cost basis</dt><dd>{formatMoney(group.costBasisEurMinor, EUR)}</dd></div><div><dt>Unrealized P&amp;L</dt><dd className={pnlClass(group.unrealizedPnlMinor)}>{formatMoney(group.unrealizedPnlMinor, EUR)} / {percent(group.returnPercent)}</dd></div><div><dt>Valuation evidence</dt><dd>{group.mixedEvidence ? `Mixed, oldest ${formatDate(group.valuedAt)}` : group.source && group.source !== "MANUAL" && group.valuedAt && group.lots.some((lot) => staleQuote(lot.holding, asOf)) ? `Stale quote, ${formatDate(group.valuedAt)}` : group.source ? `${valuationSourceLabel(group.source)}, ${formatDate(group.valuedAt)}` : "No valuation recorded"}</dd></div>{group.missingValuation && <div><dt>Value coverage</dt><dd>{group.valuedCount} of {group.lots.length} purchases valued</dd></div>}{group.pnlCoveredCount < group.lots.length && group.assetType !== "BANK_CASH" && group.assetType !== "BROKERAGE_CASH" && <div><dt>P&amp;L coverage</dt><dd>{group.pnlCoveredCount} of {group.lots.length} purchases covered</dd></div>}{group.currency !== EUR && <div><dt>Native value</dt><dd>{formatMoney(group.nativeValueMinor, group.currency)}</dd></div>}</dl><div className="holding-actions">{group.isSecurity && template && <button className="button ghost" type="button" aria-label={`Add ${group.symbol ?? group.name}${venue ? ` on ${venue}` : ""} purchase`} onClick={() => onAddPurchase(groupAssets)}><Plus aria-hidden="true" /> Add purchase</button>}{group.lots.length > 1 && <button className="button ghost" type="button" aria-expanded={isExpanded} aria-controls={`mobile-lots-${group.key}`} onClick={() => toggle(group.key)}><ChevronRight aria-hidden="true" /> {isExpanded ? "Hide" : "Show"} purchases</button>}{singleton && <HoldingActions asset={singleton} onValue={() => onValue(singleton)} onEdit={() => onEdit(singleton)} />}</div>
        {group.lots.length > 1 && isExpanded && <div className="portfolio-lot-list" id={`mobile-lots-${group.key}`}>{group.lots.map(({ asset, holding }) => <article key={holding.assetId}><header><div><strong>{formatDate(asset?.acquisitionDate)}</strong><small>{holding.quantity ?? "No quantity"} units</small></div><strong>{formatMoney(holding.eurValueMinor, EUR)}</strong></header><dl><div><dt>Cost basis</dt><dd>{formatMoney(holding.costBasisEurMinor, EUR)}</dd></div><div><dt>Unrealized P&amp;L</dt><dd className={pnlClass(holding.unrealizedPnlMinor)}>{formatMoney(holding.unrealizedPnlMinor, EUR)}</dd></div></dl><HoldingActions asset={asset} onValue={() => asset && onValue(asset)} onEdit={() => asset && onEdit(asset)} /></article>)}</div>}
      </article>;
    })}</div>
  </section>;
}
