import { useRef, useState, type FormEvent } from "react";
import { Archive, Landmark, Save } from "lucide-react";
import { ApiProblem, api } from "../../api/client";
import type { Asset, AssetCreateInput, AssetPatchInput, AssetType, FxProvenanceSource, ManualValuationInput, SupportedPortfolioCurrency } from "../../api/types";
import { Drawer } from "../../components/Drawer";
import { Field, InlineNotice } from "../../components/ui";
import { formatDate, formatMoney, localCalendarDate, minorToMajorInput, parseMajorAmount } from "../../shared/format";

export type PortfolioDrawerState =
  | { mode: "create"; template?: Asset; groupAssets?: Asset[] }
  | { mode: "edit" | "value"; asset: Asset }
  | null;

const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "BANK_CASH", label: "Bank cash" }, { value: "BROKERAGE_CASH", label: "Brokerage cash" },
  { value: "ETF", label: "ETF" }, { value: "STOCK", label: "Stock" },
  { value: "FIXED_ASSET", label: "Fixed asset" }, { value: "OTHER", label: "Other" },
];
const CURRENCIES: SupportedPortfolioCurrency[] = ["EUR", "USD", "GBP", "CHF"];
const CASH_TYPES = new Set<AssetType>(["BANK_CASH", "BROKERAGE_CASH"]);
const SECURITY_TYPES = new Set<AssetType>(["ETF", "STOCK"]);
const DECIMAL = /^(?:0|[1-9]\d{0,14})(?:\.\d{0,17}[1-9])?$/;

interface Draft {
  requestId: string;
  name: string; assetType: AssetType; currency: SupportedPortfolioCurrency; acquisitionDate: string; quantity: string;
  trackCost: boolean; costNative: string; purchaseUnitPrice: string; costFxSource: FxProvenanceSource | ""; costFxRate: string; costFxDate: string; costFxPreviewToken: string;
  quoteEnabled: boolean; symbol: string; exchange: string; micCode: string;
  valuedAt: string; nativeValue: string; unitPrice: string; fxSource: FxProvenanceSource | ""; fxRate: string; fxDate: string; fxPreviewToken: string; effectiveAt: string;
}

interface CostBasisData {
  nativeMinor: number | null;
  eurMinor: number | null;
  source: FxProvenanceSource | null;
  rate: string | null;
  rateDate: string | null;
  previewToken: string | null;
}

function createRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") globalThis.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function initialDraft(state: Exclude<PortfolioDrawerState, null>): Draft {
  const today = localCalendarDate();
  if (state.mode === "create") {
    const template = state.template;
    if (template) {
      const currency = template.currency as SupportedPortfolioCurrency;
      return {
        requestId: createRequestId(), name: template.quote?.symbol ?? template.name,
        assetType: template.assetType, currency, acquisitionDate: today, quantity: "",
        trackCost: true, costNative: "", purchaseUnitPrice: "",
        costFxSource: currency === "EUR" ? "IDENTITY" : "", costFxRate: currency === "EUR" ? "1" : "",
        costFxDate: today, costFxPreviewToken: "", quoteEnabled: true,
        symbol: template.quote?.symbol ?? template.name.toUpperCase(),
        exchange: template.quote?.exchange ?? "", micCode: template.quote?.micCode ?? "",
        valuedAt: today, nativeValue: "", unitPrice: "",
        fxSource: currency === "EUR" ? "IDENTITY" : "", fxRate: currency === "EUR" ? "1" : "",
        fxDate: today, fxPreviewToken: "", effectiveAt: today,
      };
    }
    return { requestId: createRequestId(), name: "", assetType: "BANK_CASH", currency: "EUR", acquisitionDate: today, quantity: "", trackCost: false, costNative: "", purchaseUnitPrice: "", costFxSource: "IDENTITY", costFxRate: "1", costFxDate: today, costFxPreviewToken: "", quoteEnabled: false, symbol: "", exchange: "", micCode: "", valuedAt: today, nativeValue: "", unitPrice: "", fxSource: "IDENTITY", fxRate: "1", fxDate: today, fxPreviewToken: "", effectiveAt: today };
  }
  const asset = state.asset;
  const valuation = asset.latestValuation;
  const currency = asset.currency as SupportedPortfolioCurrency;
  return {
    requestId: asset.id,
    name: asset.name, assetType: asset.assetType, currency, acquisitionDate: asset.acquisitionDate,
    quantity: asset.quantity ?? "", trackCost: asset.costBasisEurMinor != null,
    costNative: asset.costBasisNativeMinor == null ? "" : minorToMajorInput(asset.costBasisNativeMinor),
    purchaseUnitPrice: asset.costBasisNativeMinor != null && asset.quantity ? unitPriceFromPosition(asset.costBasisNativeMinor, asset.quantity) : "",
    costFxSource: validFxSource(asset.costBasisFxSource), costFxRate: asset.costBasisFxRateToEur ?? (currency === "EUR" ? "1" : ""),
    costFxDate: asset.costBasisFxRateDate ?? asset.acquisitionDate, costFxPreviewToken: "",
    quoteEnabled: asset.quote != null, symbol: asset.quote?.symbol ?? "", exchange: asset.quote?.exchange ?? "", micCode: asset.quote?.micCode ?? "",
    valuedAt: today, nativeValue: valuation ? minorToMajorInput(valuation.nativeValueMinor) : "", unitPrice: state.mode === "value" ? "" : valuation?.unitPrice ?? (valuation && asset.quantity ? unitPriceFromPosition(valuation.nativeValueMinor, asset.quantity) : ""),
    fxSource: currency === "EUR" ? "IDENTITY" : validFxSource(valuation?.fxSource), fxRate: currency === "EUR" ? "1" : valuation?.fxRateToEur ?? "",
    fxDate: currency === "EUR" ? today : valuation?.fxRateDate ?? today, fxPreviewToken: "", effectiveAt: today,
  };
}

function validFxSource(value: string | null | undefined): FxProvenanceSource | "" {
  return value === "ECB" || value === "MANUAL" || value === "IDENTITY" ? value : "";
}

function decimalError(value: string, label: string, required = false): string | null {
  if (!value) return required ? `${label} is required.` : null;
  return DECIMAL.test(value) && Number(value) > 0 ? null : `${label} must be a positive canonical decimal.`;
}

function money(value: string, label: string, required = false): { value: number | null; error: string | null } {
  if (!value.trim()) return { value: null, error: required ? `${label} is required.` : null };
  const parsed = parseMajorAmount(value);
  return parsed == null || parsed < 0
    ? { value: null, error: `${label} must be a non-negative safe amount with no more than two decimal places.` }
    : { value: parsed, error: null };
}

function decimalParts(value: string) {
  const [whole = "", fraction = ""] = value.split(".");
  return { integer: BigInt(`${whole}${fraction}`), scale: fraction.length };
}

function multiplyAndRound(leftInteger: bigint, leftScale: number, rightInteger: bigint, rightScale: number): number | null {
  const denominator = 10n ** BigInt(leftScale + rightScale);
  const numerator = leftInteger * rightInteger;
  const rounded = numerator / denominator + (numerator % denominator * 2n >= denominator ? 1n : 0n);
  const result = Number(rounded);
  return Number.isSafeInteger(result) ? result : null;
}

function positionValueMinor(quantity: string, unitPrice: string): number | null {
  if (!DECIMAL.test(quantity) || !DECIMAL.test(unitPrice)) return null;
  try {
    const left = decimalParts(quantity); const right = decimalParts(unitPrice);
    return multiplyAndRound(left.integer * 100n, left.scale, right.integer, right.scale);
  } catch { return null; }
}

function unitPriceFromPosition(nativeValueMinor: number, quantity: string): string {
  try {
    const parsed = decimalParts(quantity);
    if (parsed.integer <= 0n) return "";
    const scale = 12;
    const decimalBase = 10n ** BigInt(scale);
    const numerator = BigInt(nativeValueMinor) * 10n ** BigInt(parsed.scale) * decimalBase;
    const denominator = parsed.integer * 100n;
    const rounded = numerator / denominator + (numerator % denominator * 2n >= denominator ? 1n : 0n);
    const whole = rounded / decimalBase;
    const fraction = (rounded % decimalBase).toString().padStart(scale, "0").replace(/0+$/, "");
    const result = fraction ? `${whole}.${fraction}` : whole.toString();
    return positionValueMinor(quantity, result) === nativeValueMinor ? result : "";
  } catch {
    return "";
  }
}

function convertMinorToEur(nativeMinor: number, rate: string): number | null {
  try {
    const parsed = decimalParts(rate);
    return multiplyAndRound(BigInt(nativeMinor), 0, parsed.integer, parsed.scale);
  } catch { return null; }
}

function valuation(draft: Draft, valuedAt: string, priceBased: boolean): { data: ManualValuationInput | null; error: string | null } {
  const unitPrice = priceBased ? draft.unitPrice : "";
  const unitError = priceBased ? decimalError(unitPrice, "Price per share", true) : null;
  const calculatedNative = priceBased ? positionValueMinor(draft.quantity, unitPrice) : null;
  const native = priceBased
    ? { value: calculatedNative, error: calculatedNative == null ? "Enter a valid quantity and price per share." : null }
    : money(draft.nativeValue, "Current value", true);
  if (!valuedAt) return { data: null, error: "Valuation date is required." };
  if (native.error || unitError) return { data: null, error: native.error ?? unitError };
  if (draft.currency === "EUR") return { data: { valuedAt, nativeValueMinor: native.value!, unitPrice: unitPrice || null, fxSource: "IDENTITY", fxRateToEur: "1", fxRateDate: valuedAt }, error: null };
  const fxError = decimalError(draft.fxRate, "FX rate", true);
  if (fxError || !draft.fxDate || (draft.fxSource !== "ECB" && draft.fxSource !== "MANUAL")) return { data: null, error: fxError ?? (!draft.fxDate ? "FX rate date is required." : "Choose an ECB rate or enter a manual rate.") };
  if (draft.fxSource === "ECB" && draft.fxPreviewToken.length !== 64) return { data: null, error: "Use ECB rate again for this currency and valuation date." };
  if (draft.fxDate > valuedAt) return { data: null, error: "FX rate date cannot be after the valuation date." };
  if (convertMinorToEur(native.value!, draft.fxRate) == null) return { data: null, error: "Calculated EUR value exceeds the safe monetary range." };
  return { data: { valuedAt, nativeValueMinor: native.value!, unitPrice: unitPrice || null, fxSource: draft.fxSource, fxRateToEur: draft.fxRate, fxRateDate: draft.fxDate, ...(draft.fxSource === "ECB" && { fxPreviewToken: draft.fxPreviewToken }) }, error: null };
}

function costBasis(draft: Draft, effectiveDate: string, isCash: boolean): { data: CostBasisData; error: string | null } {
  const empty: CostBasisData = { nativeMinor: null, eurMinor: null, source: null, rate: null, rateDate: null, previewToken: null };
  if (!draft.trackCost || isCash) return { data: empty, error: null };
  const native = money(draft.costNative, "Total amount paid", true);
  if (native.error) return { data: empty, error: native.error };
  if (draft.currency === "EUR") return { data: { nativeMinor: native.value, eurMinor: native.value, source: "IDENTITY", rate: "1", rateDate: draft.costFxDate || effectiveDate, previewToken: null }, error: null };
  const rateError = decimalError(draft.costFxRate, "Cost-basis FX rate", true);
  if (rateError || !draft.costFxDate || (draft.costFxSource !== "ECB" && draft.costFxSource !== "MANUAL")) return { data: empty, error: rateError ?? (!draft.costFxDate ? "Cost-basis FX date is required." : "Choose an ECB cost rate or enter a manual rate.") };
  if (draft.costFxDate > effectiveDate) return { data: empty, error: "Cost-basis FX date cannot follow its effective date." };
  const eurMinor = convertMinorToEur(native.value!, draft.costFxRate);
  if (eurMinor == null) return { data: empty, error: "Calculated EUR cost basis exceeds the safe monetary range." };
  return { data: { nativeMinor: native.value, eurMinor, source: draft.costFxSource, rate: draft.costFxRate, rateDate: draft.costFxDate, previewToken: draft.costFxSource === "ECB" ? draft.costFxPreviewToken : null }, error: null };
}

function sameQuote(asset: Asset, draft: Draft): boolean {
  const quote = draft.quoteEnabled ? { symbol: draft.symbol.trim().toUpperCase(), exchange: draft.exchange.trim().toUpperCase() || null, micCode: draft.micCode.trim().toUpperCase() || null } : null;
  return JSON.stringify(asset.quote) === JSON.stringify(quote);
}

function FxControls({ prefix, purpose, source, rate, rateDate, maxDate, loading, pending, onPreview, onChange }: { prefix: string; purpose: string; source: FxProvenanceSource | ""; rate: string; rateDate: string; maxDate: string; loading: boolean; pending: boolean; onPreview: () => void; onChange: (patch: { source?: FxProvenanceSource; rate?: string; rateDate?: string }) => void }) {
  const status = source === "ECB" ? `ECB rate ${rate} from ${rateDate}` : source === "MANUAL" ? `Manual rate ${rate || "not entered"}` : "No conversion rate selected";
  return <div className="wide fx-rate-picker"><div className="fx-preview-action"><button className="button secondary" type="button" disabled={pending || !maxDate} onClick={onPreview}><Landmark aria-hidden="true" />{loading ? "Looking up ECB..." : "Use ECB rate"}</button><span>{status}</span></div><details open={source === "MANUAL" || undefined}><summary>Enter a rate manually</summary><div className="form-grid"><Field label="Manual FX rate to EUR" htmlFor={`${prefix}-fx-rate`} hint={`Used to convert the ${purpose} to EUR`}><input id={`${prefix}-fx-rate`} disabled={pending} inputMode="decimal" value={rate} onChange={(event) => onChange({ rate: event.target.value, source: "MANUAL" })} placeholder="0.92" /></Field><Field label="Rate date" htmlFor={`${prefix}-fx-date`}><input id={`${prefix}-fx-date`} disabled={pending} type="date" max={maxDate} value={rateDate} onChange={(event) => onChange({ rateDate: event.target.value, source: "MANUAL" })} /></Field></div></details></div>;
}

export function PortfolioDrawer({ state, onClose, onSaved, onConflict }: { state: Exclude<PortfolioDrawerState, null>; onClose: () => void; onSaved: (message: string, tone?: "good" | "warn") => void; onConflict: () => void }) {
  const [draft, setDraft] = useState(() => initialDraft(state));
  const [busy, setBusy] = useState(false);
  const [fxBusy, setFxBusy] = useState<"cost" | "valuation" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fxRequestId = useRef(0);
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const activeState = state;
  const update = (patch: Partial<Draft>) => { setError(null); setDraft((current) => ({ ...current, ...patch })); };
  const showError = (message: string) => { setError(message); requestAnimationFrame(() => errorSummaryRef.current?.focus()); };
  const isCash = CASH_TYPES.has(draft.assetType);
  const isSecurity = SECURITY_TYPES.has(draft.assetType);
  const isValue = activeState.mode === "value";
  const asset = activeState.mode === "create" ? null : activeState.asset;
  const identityLocked = activeState.mode === "create" && Boolean(activeState.template);
  const valuationDate = activeState.mode === "edit" ? draft.effectiveAt : draft.valuedAt;
  const costDate = isSecurity ? draft.acquisitionDate : activeState.mode === "create" ? draft.acquisitionDate : draft.effectiveAt;
  const priceBasedValue = isSecurity && (activeState.mode === "create" || Boolean(draft.quantity));
  const nativeValueMinor = priceBasedValue ? positionValueMinor(draft.quantity, draft.unitPrice) : parseMajorAmount(draft.nativeValue);
  const estimatedEur = draft.currency !== "EUR" && nativeValueMinor != null && DECIMAL.test(draft.fxRate) ? convertMinorToEur(nativeValueMinor, draft.fxRate) : null;
  const securityPurchaseMinor = isSecurity ? positionValueMinor(draft.quantity, draft.purchaseUnitPrice) : null;
  const costNativeMinor = isSecurity ? securityPurchaseMinor : parseMajorAmount(draft.costNative);
  const estimatedCostEur = draft.currency === "EUR" ? costNativeMinor : costNativeMinor != null && DECIMAL.test(draft.costFxRate) ? convertMinorToEur(costNativeMinor, draft.costFxRate) : null;
  const draftCostNative = !draft.trackCost || isCash ? null : costNativeMinor;
  const draftCostEur = !draft.trackCost || isCash ? null : estimatedCostEur;
  const draftCostSource = !draft.trackCost || isCash ? null : draft.currency === "EUR" ? "IDENTITY" : draft.costFxSource || null;
  const draftCostRate = !draft.trackCost || isCash ? null : draft.currency === "EUR" ? "1" : draft.costFxRate || null;
  const draftCostDate = !draft.trackCost || isCash ? null : draft.costFxDate || null;
  const costInputsChanged = asset != null && (
    draftCostNative !== asset.costBasisNativeMinor || draftCostEur !== asset.costBasisEurMinor ||
    draftCostSource !== asset.costBasisFxSource || draftCostRate !== asset.costBasisFxRateToEur ||
    draftCostDate !== asset.costBasisFxRateDate
  );
  const hasPositionChanges = activeState.mode === "edit" && ((draft.quantity || null) !== activeState.asset.quantity || costInputsChanged);
  const showValueSection = isValue || (!isSecurity && (activeState.mode !== "edit" || hasPositionChanges));
  const totalValueLabel = nativeValueMinor == null ? "Enter quantity and price" : formatMoney(nativeValueMinor, draft.currency);

  async function loadEcb(target: "cost" | "valuation") {
    const date = target === "cost" ? costDate : valuationDate;
    if (!date || draft.currency === "EUR" || fxBusy) return;
    const requestId = ++fxRequestId.current;
    const currency = draft.currency;
    setFxBusy(target); setError(null);
    try {
      const preview = await api.portfolio.previewFx(currency, date);
      if (requestId !== fxRequestId.current || preview.currency !== currency || preview.valuedAt !== date) return;
      setDraft((current) => {
        const currentDate = target === "cost"
          ? (SECURITY_TYPES.has(current.assetType) || activeState.mode === "create" ? current.acquisitionDate : current.effectiveAt)
          : (activeState.mode === "edit" ? current.effectiveAt : current.valuedAt);
        if (current.currency !== currency || currentDate !== date) return current;
        return { ...current, ...(target === "cost"
          ? { costFxSource: preview.source, costFxRate: preview.rateToEur, costFxDate: preview.rateDate, costFxPreviewToken: preview.previewToken }
          : { fxSource: preview.source, fxRate: preview.rateToEur, fxDate: preview.rateDate, fxPreviewToken: preview.previewToken }) };
      });
    } catch (caught) { showError(caught instanceof Error ? caught.message : "The ECB rate could not be loaded."); }
    finally { if (requestId === fxRequestId.current) setFxBusy(null); }
  }

  function validateIdentity(): string | null {
    if (!draft.name.trim()) return "Asset name is required.";
    if (!CURRENCIES.includes(draft.currency)) return "Choose a supported portfolio currency.";
    if (!draft.acquisitionDate) return "Acquisition date is required.";
    const quantityError = decimalError(draft.quantity, "Number of shares", isSecurity);
    if (quantityError) return quantityError;
    if (isSecurity && activeState.mode === "create" && !draft.symbol.trim()) return "Ticker is required to fetch the current price.";
    if (isSecurity && activeState.mode === "create" && !draft.exchange.trim() && !draft.micCode.trim()) return "Exchange or MIC code is required to fetch the current price.";
    if (isSecurity && activeState.mode === "edit" && (!draft.symbol.trim() || (!draft.exchange.trim() && !draft.micCode.trim()))) return "Ticker and exchange are required to fetch the current price.";
    return null;
  }

  async function automaticFx(valuedAt: string) {
    if (draft.currency === "EUR") return { source: "IDENTITY" as const, rate: "1", rateDate: valuedAt, previewToken: null };
    const preview = await api.portfolio.previewFx(draft.currency, valuedAt);
    if (preview.currency !== draft.currency || preview.valuedAt !== valuedAt) throw new Error("The ECB rate did not match the requested currency and date.");
    return { source: "ECB" as const, rate: preview.rateToEur, rateDate: preview.rateDate, previewToken: preview.previewToken };
  }

  async function saveAutomaticQuote(current: Asset, groupAssets: Asset[] = []): Promise<{ warning: string | null; valuedAt: string | null }> {
    if (!current.quote) return { warning: "The latest price could not be fetched because the quote configuration is incomplete.", valuedAt: null };
    try {
      const quoted = new Map(
        [current, ...groupAssets]
          .filter((asset) => asset.isActive && asset.quote)
          .map((asset) => [asset.id, asset]),
      );
      const previews = await api.portfolio.previewQuotes([...quoted.keys()]);
      const ready = previews.filter((preview) => preview.status === "ready");
      const currentPreview = ready.find((preview) => preview.assetId === current.id);
      const failures = previews.filter((preview) => preview.status === "error");
      if (!ready.length) return { warning: failures[0]?.status === "error" ? failures[0].error.message : "The market data service returned no latest price.", valuedAt: null };
      await api.portfolio.saveQuoteSnapshots(ready);
      const warning = failures.length
        ? `${failures.length} grouped purchase quote${failures.length === 1 ? "" : "s"} could not be refreshed. ${failures.map((failure) => failure.status === "error" ? failure.error.message : "").join(" ")}`
        : null;
      return { warning, valuedAt: currentPreview?.valuedAt ?? null };
    } catch (caught) {
      return { warning: caught instanceof Error ? caught.message : "The latest price could not be fetched.", valuedAt: null };
    }
  }

  async function saveAutomaticHistory(current: Asset): Promise<{ saved: number; warning: string | null }> {
    const supportedVenues = new Set(["LSEETF", "LSE", "XLON", "AEB", "AMS", "XAMS", "IBIS2", "XETRA", "GER", "XETR"]);
    const venues = [current.quote?.exchange, current.quote?.micCode];
    if (!venues.some((venue) => venue && supportedVenues.has(venue))) return { saved: 0, warning: null };
    try {
      const preview = await api.portfolio.previewQuoteHistory(current.id);
      if (!preview.items.length) return { saved: 0, warning: null };
      await api.portfolio.saveQuoteSnapshots(preview.items);
      return { saved: preview.items.length, warning: null };
    } catch (caught) {
      return { saved: 0, warning: caught instanceof Error ? caught.message : "Monthly history could not be loaded." };
    }
  }

  async function saveSecurity() {
    const purchaseError = decimalError(draft.purchaseUnitPrice, "Purchase price per share", true);
    const purchaseNative = positionValueMinor(draft.quantity, draft.purchaseUnitPrice);
    if (activeState.mode === "create" && (purchaseError || purchaseNative == null)) { showError(purchaseError ?? "Enter a valid number of shares and purchase price."); return; }
    const quote = activeState.mode === "create"
      ? { symbol: draft.symbol.trim().toUpperCase(), exchange: draft.exchange.trim().toUpperCase() || null, micCode: draft.micCode.trim().toUpperCase() || null }
      : { symbol: draft.symbol.trim().toUpperCase(), exchange: draft.exchange.trim().toUpperCase() || null, micCode: draft.micCode.trim().toUpperCase() || null };
    setBusy(true); setError(null);
    try {
      if (activeState.mode === "create") {
        if (purchaseNative == null) throw new Error("Enter a valid number of shares and purchase price.");
        const purchaseFx = await automaticFx(draft.acquisitionDate);
        const purchaseEur = convertMinorToEur(purchaseNative, purchaseFx.rate);
        if (purchaseEur == null) throw new Error("The calculated purchase value is too large.");
        const input: AssetCreateInput = {
          id: draft.requestId,
          name: draft.name.trim().toUpperCase(), assetType: draft.assetType, currency: draft.currency,
          acquisitionDate: draft.acquisitionDate, quantity: draft.quantity,
          costBasisNativeMinor: purchaseNative, costBasisEurMinor: purchaseEur,
          costBasisFxSource: purchaseFx.source, costBasisFxRateToEur: purchaseFx.rate,
          costBasisFxRateDate: purchaseFx.rateDate, costBasisFxPreviewToken: purchaseFx.previewToken,
          quote,
          initialValuation: {
            valuedAt: draft.acquisitionDate, nativeValueMinor: purchaseNative, unitPrice: draft.purchaseUnitPrice,
            fxSource: purchaseFx.source, fxRateToEur: purchaseFx.rate, fxRateDate: purchaseFx.rateDate,
            ...(purchaseFx.previewToken && { fxPreviewToken: purchaseFx.previewToken }),
          },
        };
        const created = await api.assets.create(input);
        const quoteResult = await saveAutomaticQuote(created, activeState.groupAssets ?? []);
        const historyResult = await saveAutomaticHistory(created);
        const warnings = [quoteResult.warning, historyResult.warning].filter(Boolean).join(" ");
        const success = `Added ${created.name}${quoteResult.valuedAt ? ` with its latest price from ${formatDate(quoteResult.valuedAt)}` : ""}${historyResult.saved ? ` and ${historyResult.saved} monthly history points` : ""}.`;
        onSaved(warnings ? `${success} ${warnings}` : success, warnings ? "warn" : "good");
      } else {
        const original = activeState.asset;
        const patch: AssetPatchInput = { expectedRevision: original.revision };
        if (draft.name.trim() !== original.name) patch.name = draft.name.trim();
        if (!sameQuote(original, { ...draft, quoteEnabled: true })) patch.quote = quote;
        const updated = Object.keys(patch).length > 1 ? await api.assets.patch(original.id, patch) : original;
        const quoteResult = await saveAutomaticQuote(updated);
        const historyResult = await saveAutomaticHistory(updated);
        const warnings = [quoteResult.warning, historyResult.warning].filter(Boolean).join(" ");
        const success = `Updated ${updated.name}${quoteResult.valuedAt ? ` with its latest price from ${formatDate(quoteResult.valuedAt)}` : ""}${historyResult.saved ? ` and ${historyResult.saved} monthly history points` : ""}.`;
        onSaved(warnings ? `${success} ${warnings}` : success, warnings ? "warn" : "good");
      }
      onClose();
    } catch (caught) {
      if (caught instanceof ApiProblem && caught.status === 409) onConflict();
      showError(caught instanceof Error ? caught.message : "The investment could not be saved.");
    } finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const identityError = isValue ? null : validateIdentity();
    if (identityError) { showError(identityError); return; }
    if (isSecurity && !isValue) { await saveSecurity(); return; }
    const costResult = costBasis(draft, costDate, isCash);
    if (costResult.error) { showError(costResult.error); return; }
    const original = activeState.mode === "edit" ? activeState.asset : null;
    const quantity = draft.quantity || null;
    const costChanged = original != null && (costResult.data.nativeMinor !== original.costBasisNativeMinor || costResult.data.eurMinor !== original.costBasisEurMinor || costResult.data.source !== original.costBasisFxSource || costResult.data.rate !== original.costBasisFxRateToEur || costResult.data.rateDate !== original.costBasisFxRateDate);
    const positionChanged = original != null && (quantity !== original.quantity || costChanged);
    if ((activeState.mode === "create" || costChanged) && costResult.data.source === "ECB" && costResult.data.previewToken?.length !== 64) { showError("Use ECB rate again for this currency and purchase-cost date."); return; }
    const needsValuation = activeState.mode !== "edit" || positionChanged;
    const valuationResult = needsValuation ? valuation(draft, valuationDate, priceBasedValue) : { data: null, error: null };
    if (valuationResult.error || (needsValuation && !valuationResult.data)) { showError(valuationResult.error ?? "Add a value for this date."); return; }
    if (needsValuation && valuationDate < draft.acquisitionDate) { showError("Value date cannot be before acquisition."); return; }
    setBusy(true); setError(null);
    try {
      if (activeState.mode === "create") {
        const input: AssetCreateInput = {
          id: draft.requestId,
          name: draft.name.trim(), assetType: draft.assetType, currency: draft.currency, acquisitionDate: draft.acquisitionDate,
          quantity: draft.quantity || null, costBasisNativeMinor: costResult.data.nativeMinor, costBasisEurMinor: costResult.data.eurMinor,
          costBasisFxSource: costResult.data.source, costBasisFxRateToEur: costResult.data.rate, costBasisFxRateDate: costResult.data.rateDate,
          costBasisFxPreviewToken: costResult.data.previewToken,
          quote: draft.quoteEnabled ? { symbol: draft.symbol.trim().toUpperCase(), exchange: draft.exchange.trim().toUpperCase() || null, micCode: draft.micCode.trim().toUpperCase() || null } : null,
          initialValuation: valuationResult.data!,
        };
        await api.assets.create(input); onSaved(`Added ${input.name}.`);
      } else if (activeState.mode === "value") {
        await api.assets.addValuation(activeState.asset.id, { expectedRevision: activeState.asset.revision, ...valuationResult.data! }); onSaved(`Recorded a valuation for ${activeState.asset.name}.`);
      } else {
        const original = activeState.asset;
        const patch: AssetPatchInput = { expectedRevision: original.revision };
        if (draft.name.trim() !== original.name) patch.name = draft.name.trim();
        if (quantity !== original.quantity) patch.quantity = quantity;
        if (costChanged) {
          patch.costBasisNativeMinor = costResult.data.nativeMinor; patch.costBasisEurMinor = costResult.data.eurMinor;
          patch.costBasisFxSource = costResult.data.source; patch.costBasisFxRateToEur = costResult.data.rate; patch.costBasisFxRateDate = costResult.data.rateDate;
          patch.costBasisFxPreviewToken = costResult.data.previewToken;
        }
        if (!sameQuote(original, draft)) patch.quote = draft.quoteEnabled ? { symbol: draft.symbol.trim().toUpperCase(), exchange: draft.exchange.trim().toUpperCase() || null, micCode: draft.micCode.trim().toUpperCase() || null } : null;
        if (positionChanged) { patch.effectiveAt = draft.effectiveAt; patch.replacementValuation = valuationResult.data!; }
        if (Object.keys(patch).length === 1) { showError("Change at least one asset field before saving."); setBusy(false); return; }
        await api.assets.patch(original.id, patch); onSaved(`Updated ${original.name}.`);
      }
      onClose();
    } catch (caught) {
      if (caught instanceof ApiProblem && caught.status === 409) onConflict();
      showError(caught instanceof Error ? caught.message : "The portfolio change could not be saved.");
    } finally { setBusy(false); }
  }

  async function archive() {
    if (!asset || !window.confirm(`Archive "${asset.name}"? Its history remains available, but it leaves the active portfolio.`)) return;
    setBusy(true); setError(null);
    try { await api.assets.patch(asset.id, { expectedRevision: asset.revision, isActive: false }); onSaved(`Archived ${asset.name}.`); onClose(); }
    catch (caught) { if (caught instanceof ApiProblem && caught.status === 409) onConflict(); showError(caught instanceof Error ? caught.message : "The asset could not be archived."); }
    finally { setBusy(false); }
  }

  const title = activeState.mode === "create" && identityLocked ? `Add ${draft.name} purchase` : activeState.mode === "create" ? "Add asset" : activeState.mode === "value" ? `Value ${activeState.asset.name}` : `Edit ${activeState.asset.name}`;
  const description = activeState.mode === "create" && identityLocked ? "Add a dated purchase to this ticker position." : activeState.mode === "create" && isSecurity ? "Enter what you bought. The latest available price and P&L are calculated automatically." : activeState.mode === "create" ? "Add the asset and what it is worth now." : isValue ? "Record what this asset was worth on a specific date." : "Change the details you use to track this asset.";
  const valueHeading = activeState.mode === "create" ? "Current value" : activeState.mode === "value" ? "New value" : "Value after this change";
  const totalInputLabel = isCash ? `Current balance (${draft.currency})` : draft.assetType === "FIXED_ASSET" ? `Estimated value (${draft.currency})` : `Current value (${draft.currency})`;
  return <Drawer open title={title} description={description} dismissible={!busy} onClose={onClose}>
    <form onSubmit={submit}>
      {error && <div className="portfolio-form-error" ref={errorSummaryRef} tabIndex={-1}><InlineNotice tone="bad">{error}</InlineNotice></div>}
      <fieldset className="portfolio-form-fields" disabled={busy || Boolean(fxBusy)}>
      {!isValue && <><section className="portfolio-form-section"><h3>Asset details</h3><div className="form-grid">
        <Field label={activeState.mode === "create" && isSecurity ? "Ticker" : "Asset name"} htmlFor="asset-name" hint={identityLocked ? "Fixed by the selected ticker group" : activeState.mode === "create" && isSecurity ? "For example: CSPX" : undefined}><input id="asset-name" disabled={identityLocked} value={draft.name} onChange={(event) => update({ name: event.target.value, ...(activeState.mode === "create" && isSecurity && { symbol: event.target.value.toUpperCase() }) })} /></Field>
        <Field label="Asset type" htmlFor="asset-type" hint={asset || identityLocked ? "Asset type is fixed" : undefined}><select id="asset-type" disabled={Boolean(asset) || identityLocked} value={draft.assetType} onChange={(event) => { const assetType = event.target.value as AssetType; const security = SECURITY_TYPES.has(assetType); update({ assetType, trackCost: security || (!CASH_TYPES.has(assetType) && draft.trackCost), quoteEnabled: security, symbol: security ? draft.name.trim().toUpperCase() : "", ...(!security && isSecurity && { quantity: "", purchaseUnitPrice: "", unitPrice: "" }) }); }}>{ASSET_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
        <Field label="Currency" htmlFor="asset-currency" hint={asset || identityLocked ? "Currency is fixed" : "Supported: EUR, USD, GBP, CHF"}><select id="asset-currency" disabled={Boolean(asset) || identityLocked || Boolean(fxBusy)} value={draft.currency} onChange={(event) => { const currency = event.target.value as SupportedPortfolioCurrency; update({ currency, costFxSource: currency === "EUR" ? "IDENTITY" : "", costFxRate: currency === "EUR" ? "1" : "", costFxDate: draft.acquisitionDate, costFxPreviewToken: "", fxSource: currency === "EUR" ? "IDENTITY" : "", fxRate: currency === "EUR" ? "1" : "", fxDate: valuationDate, fxPreviewToken: "" }); }}>{CURRENCIES.map((currency) => <option key={currency}>{currency}</option>)}</select></Field>
        <Field label={isSecurity ? "Date bought" : "Acquisition date"} htmlFor="asset-acquired" hint={asset ? "This date is fixed after creation" : undefined}><input id="asset-acquired" type="date" disabled={Boolean(asset) || Boolean(fxBusy)} value={draft.acquisitionDate} onChange={(event) => update({ acquisitionDate: event.target.value, costFxDate: event.target.value, costFxPreviewToken: "" })} /></Field>
        {isSecurity && <Field label="Number of shares" htmlFor="asset-quantity" hint={asset ? "Purchase details are fixed after creation" : undefined}><input id="asset-quantity" disabled={Boolean(asset)} inputMode="decimal" value={draft.quantity} onChange={(event) => update({ quantity: event.target.value })} placeholder="2" /></Field>}
      </div></section>
      {isSecurity && <section className="portfolio-form-section portfolio-purchase-section"><h3>Purchase</h3><div className="form-grid"><Field label={`Purchase price per share (${draft.currency})`} htmlFor="purchase-unit-price" hint={asset ? "Purchase details are fixed after creation" : "The price on your broker confirmation"}><input id="purchase-unit-price" disabled={Boolean(asset)} inputMode="decimal" value={draft.purchaseUnitPrice} onChange={(event) => update({ purchaseUnitPrice: event.target.value })} placeholder="465.06" /></Field><div className="portfolio-derived-value" aria-live="polite" aria-atomic="true"><span>Total amount paid</span><strong>{securityPurchaseMinor == null ? "Enter shares and purchase price" : formatMoney(securityPurchaseMinor, draft.currency)}</strong><small>{draft.quantity || "0"} shares × {draft.purchaseUnitPrice || "purchase price"}</small></div></div><p className="portfolio-form-intro">{asset ? "To replace an incorrect purchase, archive this asset and add it again. This keeps historical values trustworthy." : "The purchase-date ECB conversion is added automatically. You do not need to enter a cost basis or FX rate."}</p></section>}
      {!isCash && !isSecurity && <section className="portfolio-form-section"><h3>Profit and loss</h3><label className="checkbox-field"><input type="checkbox" checked={draft.trackCost} onChange={(event) => update({ trackCost: event.target.checked })} /> Track profit and loss</label>{draft.trackCost && <div className="form-grid"><Field label={`Total amount paid (${draft.currency})`} htmlFor="cost-native" hint="Total amount you originally paid"><input id="cost-native" inputMode="decimal" value={draft.costNative} onChange={(event) => update({ costNative: event.target.value })} placeholder="10000.00" /></Field>{draft.currency !== "EUR" && <><div className="portfolio-derived-value" aria-live="polite" aria-atomic="true"><span>Purchase cost in EUR</span><strong>{estimatedCostEur == null ? "Add a conversion rate" : formatMoney(estimatedCostEur, "EUR")}</strong><small>{draft.costFxSource || "Conversion rate required"}</small></div><FxControls prefix="cost" purpose="purchase cost" source={draft.costFxSource} rate={draft.costFxRate} rateDate={draft.costFxDate} maxDate={costDate} loading={fxBusy === "cost"} pending={Boolean(fxBusy)} onPreview={() => void loadEcb("cost")} onChange={(patch) => update({ ...(patch.source && { costFxSource: patch.source }), ...(patch.rate !== undefined && { costFxRate: patch.rate }), ...(patch.rateDate !== undefined && { costFxDate: patch.rateDate }), costFxPreviewToken: "" })} /></>}</div>}</section>}
      {isSecurity && <section className="portfolio-form-section"><h3>Latest market price</h3><p className="portfolio-form-intro">After saving, the app fetches the latest available trading-day price and calculates the value and P&amp;L for all your shares.</p><div className="form-grid">{activeState.mode === "edit" && <Field label="Ticker" htmlFor="quote-symbol"><input id="quote-symbol" value={draft.symbol} onChange={(event) => update({ symbol: event.target.value.toUpperCase() })} placeholder="CSPX" /></Field>}<Field label="Exchange" htmlFor="quote-exchange" hint={identityLocked ? "Fixed by the selected ticker group" : "Broker or Yahoo venue code, for example LSEETF, AEB, or IBIS2"}><input id="quote-exchange" disabled={identityLocked} value={draft.exchange} onChange={(event) => update({ exchange: event.target.value.toUpperCase() })} placeholder="LSEETF" /></Field><Field label="MIC code" htmlFor="quote-mic-code" hint={identityLocked ? "Fixed by the selected ticker group" : "Optional ISO market identifier"}><input id="quote-mic-code" disabled={identityLocked} value={draft.micCode} onChange={(event) => update({ micCode: event.target.value.toUpperCase() })} placeholder="XLON" /></Field></div></section>}</>}
      {showValueSection && <section className="portfolio-form-section portfolio-value-section"><h3>{valueHeading}</h3>
        {activeState.mode === "edit" && <><p className="portfolio-form-intro">Your quantity or total amount paid changed. Add the value on that date so the portfolio history stays accurate.</p><Field label="Date of change" htmlFor="effective-at"><input id="effective-at" type="date" disabled={Boolean(fxBusy)} value={draft.effectiveAt} min={asset?.latestValuation?.valuedAt} onChange={(event) => update({ effectiveAt: event.target.value, valuedAt: event.target.value, costFxPreviewToken: "", fxPreviewToken: "", ...(draft.currency === "EUR" && { fxDate: event.target.value, costFxDate: event.target.value }) })} /></Field></>}
        <div className="form-grid">
          {activeState.mode !== "edit" && <Field label="Value date" htmlFor="valued-at"><input id="valued-at" type="date" disabled={Boolean(fxBusy)} min={draft.acquisitionDate} value={draft.valuedAt} onChange={(event) => update({ valuedAt: event.target.value, fxPreviewToken: "", ...(draft.currency === "EUR" && { fxDate: event.target.value }) })} /></Field>}
          {priceBasedValue ? <><Field label={`Price per share (${draft.currency})`} htmlFor="unit-price" hint={`${draft.quantity || "0"} shares or units`}><input id="unit-price" inputMode="decimal" value={draft.unitPrice} onChange={(event) => update({ unitPrice: event.target.value })} placeholder="100.00" /></Field><div className="portfolio-derived-value" aria-live="polite" aria-atomic="true"><span>Total value</span><strong>{totalValueLabel}</strong><small>{draft.quantity || "0"} × {draft.unitPrice || "price per share"}</small></div></> : <Field label={totalInputLabel} htmlFor="native-value" hint="Enter the total amount"><input id="native-value" inputMode="decimal" value={draft.nativeValue} onChange={(event) => update({ nativeValue: event.target.value })} placeholder="10000.00" /></Field>}
          {draft.currency !== "EUR" && <><FxControls prefix="valuation" purpose="current value" source={draft.fxSource} rate={draft.fxRate} rateDate={draft.fxDate} maxDate={valuationDate} loading={fxBusy === "valuation"} pending={Boolean(fxBusy)} onPreview={() => void loadEcb("valuation")} onChange={(patch) => update({ ...(patch.source && { fxSource: patch.source }), ...(patch.rate !== undefined && { fxRate: patch.rate }), ...(patch.rateDate !== undefined && { fxDate: patch.rateDate }), fxPreviewToken: "" })} /><div className="wide portfolio-derived-value" aria-live="polite" aria-atomic="true"><span>Current value in EUR</span><strong>{estimatedEur == null ? "Add a value and conversion rate" : formatMoney(estimatedEur, "EUR")}</strong><small>{draft.fxSource || "Conversion rate required"}</small></div></>}
        </div>
      </section>}
      </fieldset>
      <div className="form-actions"><button className="button" disabled={busy || Boolean(fxBusy)}><Save aria-hidden="true" />{busy ? (isSecurity && !isValue ? "Saving and fetching price..." : "Saving...") : activeState.mode === "value" ? "Add valuation" : activeState.mode === "create" && identityLocked ? "Add purchase" : activeState.mode === "create" && isSecurity ? "Add investment" : activeState.mode === "create" ? "Add asset" : "Save changes"}</button>{activeState.mode === "edit" && <button className="button danger" type="button" disabled={busy} onClick={() => void archive()}><Archive aria-hidden="true" /> Archive asset</button>}</div>
    </form>
  </Drawer>;
}
