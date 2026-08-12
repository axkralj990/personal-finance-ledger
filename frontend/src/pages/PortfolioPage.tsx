import { useState } from "react";
import { Check, Plus, RefreshCw } from "lucide-react";
import { ApiProblem, api } from "../api/client";
import type { Asset, QuotePreviewItem } from "../api/types";
import { EmptyState, ErrorState, InlineNotice, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import { GroupedHoldings } from "../features/portfolio/GroupedHoldings";
import { AllocationCharts, PnlChart } from "../features/portfolio/PortfolioCharts";
import { PortfolioDrawer, type PortfolioDrawerState } from "../features/portfolio/PortfolioDrawer";
import { allocationByGroup, assetPositionKey, groupHoldings, holdingGroupLabel, pnlByGroup } from "../features/portfolio/grouping";
import { useResource } from "../hooks/use-resource";
import { formatDate, formatMoney } from "../shared/format";

const EUR = "EUR";
function pnlClass(value: number | null): string { return value == null ? "" : value >= 0 ? "portfolio-positive" : "portfolio-negative"; }
function percent(value: string | null): string { return value == null ? "Unavailable" : `${value}%`; }

function QuoteReview({ items, assetById, saving, saveError, onSave, onCancel }: { items: QuotePreviewItem[]; assetById: Map<string, Asset>; saving: boolean; saveError: string | null; onSave: () => void; onCancel: () => void }) {
  const ready = items.filter((item) => item.status === "ready");
  const grouped = new Map<string, { name: string; items: QuotePreviewItem[] }>();
  items.forEach((item) => {
    const asset = assetById.get(item.assetId);
    const key = asset ? assetPositionKey(asset) : `asset:${item.assetId}`;
    const current = grouped.get(key) ?? { name: asset?.name ?? item.assetId, items: [] };
    current.items.push(item);
    grouped.set(key, current);
  });
  const groups = [...grouped.entries()];
  const completeGroups = groups.filter(([, group]) => group.items.every((item) => item.status === "ready")).length;
  const partialGroups = groups.filter(([, group]) => group.items.some((item) => item.status === "ready") && group.items.some((item) => item.status === "error")).length;
  const failedGroups = groups.filter(([, group]) => group.items.every((item) => item.status === "error")).length;
  return <section className="quote-review" aria-labelledby="quote-review-title"><header><div><p className="eyebrow">Signed market-data preview</p><h2 id="quote-review-title">Review quotes before saving</h2><p>Confirm instrument identity and values. Nothing below changes the portfolio until saved.</p></div><StatusBadge tone={partialGroups || failedGroups ? "warn" : "good"}>{completeGroups} ready / {partialGroups} partial / {failedGroups} failed</StatusBadge></header>
    {saveError && <InlineNotice tone="bad">{saveError}</InlineNotice>}
    <div className="quote-review-list">{groups.map(([key, group]) => {
      const groupReady = group.items.filter((item) => item.status === "ready");
      const errors = group.items.filter((item) => item.status === "error");
      const item = groupReady[0];
      if (!item) return <article className="quote-review-card quote-review-error" key={key}><header><strong>{group.name}</strong><StatusBadge tone="bad">Preview failed</StatusBadge></header><p>{errors[0]?.status === "error" ? errors[0].error.message : "No purchase could be quoted."}</p><small>{errors.length} purchase{errors.length === 1 ? "" : "s"} failed</small></article>;
      const venue = item.quote.exchange ?? item.quote.micCode ?? "Venue unavailable";
      const prices = new Set(groupReady.map((preview) => preview.status === "ready" ? preview.unitPrice : ""));
      const providers = new Set(groupReady.map((preview) => preview.status === "ready" ? preview.source : ""));
      const fxEvidence = new Set(groupReady.map((preview) => preview.status === "ready" ? `${preview.fx.source}:${preview.fx.rateToEur}:${preview.fx.rateDate}` : ""));
      const valuationDates = new Set(groupReady.map((preview) => preview.status === "ready" ? preview.valuedAt : ""));
      const instruments = new Set(groupReady.map((preview) => preview.status === "ready" ? `${preview.quote.symbol}:${preview.quote.exchange ?? ""}:${preview.quote.micCode ?? ""}:${preview.quote.name}:${preview.nativeCurrency}` : ""));
      const nativeValue = groupReady.reduce((total, preview) => total + (preview.status === "ready" ? preview.nativeValueMinor : 0), 0);
      const eurValue = groupReady.reduce((total, preview) => total + (preview.status === "ready" ? preview.eurValueMinor : 0), 0);
      return <article className={`quote-review-card ${errors.length ? "quote-review-partial" : ""}`} key={key}><header><div><strong>{item.quote.name}</strong><span>{group.name} / {group.items.length} purchase{group.items.length === 1 ? "" : "s"}</span></div><StatusBadge tone={errors.length ? "warn" : "good"}>{groupReady.length} ready{errors.length ? ` / ${errors.length} failed` : ""}</StatusBadge></header><dl><div><dt>Provider</dt><dd>{providers.size > 1 ? "Mixed providers" : item.source === "YAHOO_FINANCE" ? "Yahoo Finance" : "Twelve Data"}</dd></div><div><dt>Instrument</dt><dd>{instruments.size > 1 ? "Mixed instruments" : `${item.quote.symbol} / ${venue}${item.quote.micCode && item.quote.micCode !== venue ? ` / ${item.quote.micCode}` : ""}`}</dd></div><div><dt>Unit price</dt><dd>{prices.size > 1 ? "Multiple prices" : item.unitPrice} {item.nativeCurrency}</dd></div><div><dt>Native value</dt><dd>{formatMoney(nativeValue, item.nativeCurrency)}</dd></div><div><dt>EUR value</dt><dd>{formatMoney(eurValue, EUR)}</dd></div><div><dt>FX evidence</dt><dd>{fxEvidence.size > 1 ? "Mixed FX evidence" : `${item.fx.source} / ${item.fx.rateToEur} / ${formatDate(item.fx.rateDate)}`}</dd></div><div><dt>Valuation date</dt><dd>{valuationDates.size > 1 ? "Multiple dates" : formatDate(item.valuedAt)}</dd></div></dl>{errors.length > 0 && <p>{errors.map((error) => error.status === "error" ? error.error.message : "").filter((message, index, all) => message && all.indexOf(message) === index).join(" ")}</p>}</article>;
    })}</div>
    <div className="form-actions"><button className="button" type="button" disabled={!ready.length || saving} onClick={onSave}><Check aria-hidden="true" />{saving ? "Saving reviewed quotes..." : `Save reviewed purchases (${ready.length})`}</button><button className="button secondary" type="button" disabled={saving} onClick={onCancel}>Discard preview</button></div>
  </section>;
}

export default function PortfolioPage() {
  const portfolio = useResource(() => api.portfolio.get(), "portfolio-report");
  const assets = useResource(() => api.assets.list(), "portfolio-assets");
  const [drawer, setDrawer] = useState<PortfolioDrawerState>(null);
  const [notice, setNotice] = useState<{ tone: "good" | "bad" | "warn"; text: string } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [savingQuotes, setSavingQuotes] = useState(false);
  const [quoteReview, setQuoteReview] = useState<QuotePreviewItem[] | null>(null);
  const [quoteSaveError, setQuoteSaveError] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const data = portfolio.data;
  const assetById = new Map((assets.data ?? []).map((asset) => [asset.id, asset]));
  const groups = groupHoldings(data?.holdings ?? [], assets.data ?? []);
  const groupedAllocation = allocationByGroup(groups, data?.knownValueMinor ?? 0);
  const groupedPnl = pnlByGroup(groups);
  const valuedPositions = groups.filter((group) => !group.missingValuation).length;
  const pnlEligiblePositions = groups.filter((group) => !["BANK_CASH", "BROKERAGE_CASH"].includes(group.assetType)).length;
  const pnlCoveredPositions = groups.filter((group) => !["BANK_CASH", "BROKERAGE_CASH"].includes(group.assetType) && group.pnlCoveredCount === group.lots.length).length;
  const waitingAssetIds = new Set((data?.holdings ?? []).filter((holding) => {
    const asset = assetById.get(holding.assetId);
    return Boolean(asset?.quote && holding.source === "MANUAL" && holding.costBasisEurMinor != null && holding.unrealizedPnlMinor == null);
  }).map((holding) => holding.assetId));
  const waitingForMarketPrice = groups.filter((group) => group.lots.some((lot) => waitingAssetIds.has(lot.holding.assetId)));
  const managementAvailable = Boolean(assets.data) && !assets.error;
  const portfolioMutationBusy = previewing || savingQuotes || historyBusy || Boolean(quoteReview);
  const reload = () => { setQuoteReview(null); setQuoteSaveError(null); portfolio.reload(); assets.reload(); };
  const openDrawer = (state: Exclude<PortfolioDrawerState, null>) => managementAvailable && setDrawer(state);

  async function previewQuotes() {
    const quoted = (assets.data ?? []).filter((asset) => asset.isActive && asset.quote);
    if (!quoted.length) { setNotice({ tone: "warn", text: "No active ETF or stock has a quote configuration." }); return; }
    setPreviewing(true); setNotice(null); setQuoteReview(null); setQuoteSaveError(null);
    try { setQuoteReview(await api.portfolio.previewQuotes(quoted.map((asset) => asset.id))); }
    catch (caught) { setNotice({ tone: "bad", text: caught instanceof Error ? caught.message : "Quotes could not be previewed." }); }
    finally { setPreviewing(false); }
  }

  async function saveReviewedQuotes() {
    const ready = quoteReview?.filter((item) => item.status === "ready") ?? [];
    if (!ready.length) return;
    setSavingQuotes(true); setQuoteSaveError(null);
    try {
      await api.portfolio.saveQuoteSnapshots(ready);
      const failures = (quoteReview?.length ?? 0) - ready.length;
      setNotice({ tone: failures ? "warn" : "good", text: `${ready.length} reviewed quote${ready.length === 1 ? "" : "s"} saved${failures ? `; ${failures} preview failure${failures === 1 ? "" : "s"} left previous values unchanged` : ""}.` });
      reload();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Reviewed quotes could not be saved.";
      setQuoteSaveError(`No quote values were changed. ${message}`);
      if (caught instanceof ApiProblem && caught.status === 409) { setNotice({ tone: "warn", text: "Portfolio revisions changed while quotes were under review. Reloaded current data; preview again." }); reload(); }
    } finally { setSavingQuotes(false); }
  }

  async function updateHistory() {
    const quoted = (assets.data ?? []).filter((asset) => asset.isActive && asset.quote && [asset.quote.exchange, asset.quote.micCode].some((venue) => venue === "LSE" || venue === "XLON"));
    if (!quoted.length) { setNotice({ tone: "warn", text: "No active asset supports automatic monthly history." }); return; }
    setHistoryBusy(true); setNotice(null);
    let saved = 0;
    const failures: string[] = [];
    for (const asset of quoted) {
      try {
        const preview = await api.portfolio.previewQuoteHistory(asset.id);
        if (preview.items.length) {
          await api.portfolio.saveQuoteSnapshots(preview.items);
          saved += preview.items.length;
        }
      } catch (caught) {
        failures.push(`${asset.name}: ${caught instanceof Error ? caught.message : "History could not be loaded."}`);
      }
    }
    setNotice({ tone: failures.length ? "warn" : "good", text: failures.length ? `${saved} monthly snapshot${saved === 1 ? "" : "s"} saved. ${failures.join(" ")}` : saved ? `${saved} monthly snapshot${saved === 1 ? "" : "s"} saved.` : "Monthly market history is already current." });
    reload(); setHistoryBusy(false);
  }

  return <div className="portfolio-page">
    <PageHeader eyebrow="Portfolio / EUR valuation ledger" title="Capital, with provenance" description="A dated record of manually managed holdings. Values stay separate from transaction balances and remain explicit when coverage is incomplete." actions={<><button className="button secondary" type="button" disabled={!managementAvailable || portfolioMutationBusy} onClick={() => void updateHistory()}><RefreshCw className={historyBusy ? "spin" : ""} aria-hidden="true" />{historyBusy ? "Updating history..." : "Update history"}</button><button className="button secondary" type="button" disabled={!managementAvailable || portfolioMutationBusy} onClick={() => void previewQuotes()}><RefreshCw className={previewing ? "spin" : ""} aria-hidden="true" />{previewing ? "Previewing..." : "Refresh quotes"}</button><button className="button" type="button" disabled={!managementAvailable || portfolioMutationBusy} onClick={() => openDrawer({ mode: "create" })}><Plus aria-hidden="true" /> Add asset</button></>} />
    {notice && <InlineNotice tone={notice.tone}>{notice.text}</InlineNotice>}
    {assets.error && data && <InlineNotice tone="warn">Asset management is unavailable: {assets.error.message} The portfolio report remains available in read-only mode. <button className="button ghost" type="button" onClick={assets.reload}>Retry management data</button></InlineNotice>}
    {assets.loading && data && <InlineNotice>Loading management controls. Portfolio reporting remains available.</InlineNotice>}
    {quoteReview && <QuoteReview items={quoteReview} assetById={assetById} saving={savingQuotes} saveError={quoteSaveError} onSave={() => void saveReviewedQuotes()} onCancel={() => { setQuoteReview(null); setQuoteSaveError(null); }} />}

    {portfolio.loading ? <LoadingState label="Reconciling portfolio valuations" />
      : portfolio.error ? <ErrorState error={portfolio.error} retry={reload} />
      : !data ? null
      : <>
        {!data.assetCount && <><EmptyState title="No active assets" description="Add cash, a security, a fixed asset, or another holding with its first valuation." action={<button className="button" type="button" disabled={!managementAvailable} onClick={() => openDrawer({ mode: "create" })}><Plus aria-hidden="true" /> Add first asset</button>} /><AllocationCharts byType={data.allocationByType} byAsset={data.allocationByAsset} /></>}
        {data.assetCount > 0 && <>
          {!data.complete && <InlineNotice tone="warn"><strong>Portfolio value is incomplete.</strong> {groups.length - valuedPositions} position{groups.length - valuedPositions === 1 ? " has" : "s have"} one or more purchases without a valuation. The known value excludes those purchases in {groups.filter((group) => group.missingValuation).map((group) => holdingGroupLabel(group, groups)).join(", ")}.</InlineNotice>}
          {waitingForMarketPrice.length > 0 && <InlineNotice tone="warn"><strong>Latest market price unavailable.</strong> P&amp;L for {waitingForMarketPrice.map((group) => holdingGroupLabel(group, groups)).join(", ")} is unavailable, not zero. The displayed manual value is the saved purchase snapshot. Save a provider quote or add a current valuation to calculate P&amp;L.</InlineNotice>}
          {pnlCoveredPositions < pnlEligiblePositions && <InlineNotice tone="warn">Unrealized P&amp;L fully covers {pnlCoveredPositions} of {pnlEligiblePositions} eligible non-cash positions. Purchases without both tracked cost and current value are excluded.</InlineNotice>}
          <section className="portfolio-kpis" aria-label="Portfolio summary">
            <article><span>{data.complete ? "Portfolio value" : "Known value"}</span><strong>{formatMoney(data.complete ? data.totalValueMinor : data.knownValueMinor, EUR)}</strong><p>{valuedPositions} of {groups.length} positions fully valued</p></article>
            <article><span>Tracked cost basis</span><strong>{formatMoney(data.trackedCostBasisMinor, EUR)}</strong><p>Covered non-cash positions</p></article>
            <article className={pnlClass(data.unrealizedPnlMinor)}><span>Unrealized P&amp;L</span><strong>{formatMoney(data.unrealizedPnlMinor, EUR)}</strong><p>{pnlCoveredPositions} of {pnlEligiblePositions} eligible positions fully covered</p></article>
            <article className={pnlClass(data.unrealizedPnlMinor)}><span>Return</span><strong>{percent(data.returnPercent)}</strong><p>On positive tracked cost</p></article>
          </section>
          <div className="portfolio-as-of"><span>As of <strong>{formatDate(data.asOf)}</strong></span><span>EUR reporting currency</span></div>
          <AllocationCharts byType={data.allocationByType} byAsset={groupedAllocation} />
          <PnlChart items={groupedPnl} />
          <GroupedHoldings groups={groups} asOf={data.asOf} onAddPurchase={(groupAssets) => openDrawer({ mode: "create", template: groupAssets[0], groupAssets })} onValue={(asset) => openDrawer({ mode: "value", asset })} onEdit={(asset) => openDrawer({ mode: "edit", asset })} />
        </>}
      </>}
    {drawer && <PortfolioDrawer state={drawer} onClose={() => setDrawer(null)} onSaved={(text, tone = "good") => { setNotice({ tone, text }); reload(); }} onConflict={() => { setNotice({ tone: "warn", text: "The asset changed in another request. Reloaded the current revision." }); setDrawer(null); reload(); }} />}
  </div>;
}
