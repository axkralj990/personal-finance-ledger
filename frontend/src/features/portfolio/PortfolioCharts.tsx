import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AllocationItem, AssetPnl } from "../../api/types";
import { EmptyState } from "../../components/ui";
import { formatMoney } from "../../shared/format";
import { ledgerColorForId } from "../dashboard/composition";

const RULE = "#d8d1c2";
const MUTED = "#686a61";
const VALUE = "#315b45";
const COST = "#a44d32";
const EUR = "EUR";

function euroAxis(value: number): string {
  return new Intl.NumberFormat("en-SG", { style: "currency", currency: EUR, notation: "compact", maximumFractionDigits: 1 }).format(value / 100);
}

function MoneyTooltip() {
  return <Tooltip formatter={(value, name) => [formatMoney(Number(value), EUR), String(name)]} contentStyle={{ background: "#fbf8f0", border: "1px solid #b9b1a3", borderRadius: 0 }} />;
}

function ChartSection({ id, marker, title, note, children }: { id: string; marker: string; title: string; note: string; children: React.ReactNode }) {
  return <section className="portfolio-chart-section" aria-labelledby={id}><header><span aria-hidden="true">{marker}</span><div><h2 id={id}>{title}</h2><p>{note}</p></div></header>{children}</section>;
}

function ExactData({ label, children }: { label: string; children: React.ReactNode }) {
  return <details className="dashboard-data"><summary>{label}</summary><div className="dashboard-table-scroll">{children}</div></details>;
}

export function AllocationCharts({ byType, byAsset }: { byType: AllocationItem[]; byAsset: AllocationItem[] }) {
  const rankedHeight = Math.max(320, byAsset.length * 34);
  return <ChartSection id="allocation-title" marker="02" title="Where value is held" note="Known EUR value only. Missing valuations are excluded rather than treated as zero.">
    {byAsset.length ? <><div className="portfolio-chart-grid"><div><h3>By asset type</h3><div className="portfolio-chart"><ResponsiveContainer width="100%" height="100%"><PieChart accessibilityLayer title="Portfolio allocation by asset type"><Pie data={byType} dataKey="valueMinor" nameKey="name" innerRadius="48%" outerRadius="78%" paddingAngle={1} isAnimationActive={false}>{byType.map((item) => <Cell key={item.key} fill={ledgerColorForId(item.key)} />)}</Pie><MoneyTooltip /><Legend /></PieChart></ResponsiveContainer></div></div><div><h3>Ranked by asset</h3><div className="portfolio-chart portfolio-chart-scroll" style={{ height: rankedHeight }}><ResponsiveContainer width="100%" height="100%"><BarChart data={byAsset} layout="vertical" accessibilityLayer margin={{ top: 4, right: 20, left: 15, bottom: 4 }} title="Portfolio allocation ranked by asset"><CartesianGrid stroke={RULE} strokeDasharray="2 5" horizontal={false} /><XAxis type="number" tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 10 }} /><YAxis type="category" dataKey="name" width={105} tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} /><MoneyTooltip /><Bar name="Known value" dataKey="valueMinor" isAnimationActive={false}>{byAsset.map((item) => <Cell key={item.key} fill={ledgerColorForId(item.key)} />)}</Bar></BarChart></ResponsiveContainer></div></div></div>
      <ExactData label="Exact allocation data"><div className="portfolio-exact-grid"><table className="data-table"><caption>Allocation by asset type</caption><thead><tr><th>Type</th><th className="amount">Known value</th><th className="amount">Share</th></tr></thead><tbody>{byType.map((item) => <tr key={item.key}><td>{item.name}</td><td className="amount">{formatMoney(item.valueMinor, EUR)}</td><td className="amount">{item.percentage == null ? "Unavailable" : `${item.percentage}%`}</td></tr>)}</tbody></table><table className="data-table"><caption>Ranked allocation by asset</caption><thead><tr><th>Rank</th><th>Asset</th><th className="amount">Known value</th><th className="amount">Share</th></tr></thead><tbody>{byAsset.map((item, index) => <tr key={item.key}><td>{index + 1}</td><td>{item.name}</td><td className="amount">{formatMoney(item.valueMinor, EUR)}</td><td className="amount">{item.percentage == null ? "Unavailable" : `${item.percentage}%`}</td></tr>)}</tbody></table></div></ExactData></> : <EmptyState title="No known allocation" description="Add a valuation to include an asset in allocation." />}
  </ChartSection>;
}

export function PnlChart({ items }: { items: AssetPnl[] }) {
  const covered = items.filter((item) => item.unrealizedPnlMinor != null);
  const chartHeight = Math.max(320, covered.length * 34);
  return <ChartSection id="pnl-title" marker="03" title="Unrealized result by asset" note="Cash is excluded. Assets without both cost basis and valuation remain visible in the exact table.">
    {covered.length ? <div className="portfolio-chart portfolio-chart-wide portfolio-chart-scroll" style={{ height: chartHeight }}><ResponsiveContainer width="100%" height="100%"><BarChart data={covered} layout="vertical" accessibilityLayer margin={{ top: 12, right: 18, left: 18, bottom: 8 }} title="Unrealized profit and loss by asset"><CartesianGrid stroke={RULE} strokeDasharray="2 5" horizontal={false} /><XAxis type="number" tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 10 }} /><YAxis type="category" dataKey="name" width={115} tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} /><MoneyTooltip /><ReferenceLine x={0} stroke="#272923" /><Bar name="Unrealized P&L" dataKey="unrealizedPnlMinor" isAnimationActive={false}>{covered.map((item) => <Cell key={item.assetId} fill={(item.unrealizedPnlMinor ?? 0) >= 0 ? VALUE : COST} />)}</Bar></BarChart></ResponsiveContainer></div> : <EmptyState title="No covered P&amp;L" description="Track acquisition cost on a non-cash asset and add a valuation to calculate unrealized P&amp;L." />}
    <ExactData label="Exact unrealized P&amp;L data"><table className="data-table"><caption className="sr-only">Exact unrealized profit and loss by asset</caption><thead><tr><th>Asset</th><th className="amount">Cost basis</th><th className="amount">Current value</th><th className="amount">Unrealized P&amp;L</th><th className="amount">Return</th></tr></thead><tbody>{items.map((item) => <tr key={item.assetId}><td>{item.name}</td><td className="amount">{formatMoney(item.costBasisEurMinor, EUR)}</td><td className="amount">{formatMoney(item.currentValueEurMinor, EUR)}</td><td className="amount">{formatMoney(item.unrealizedPnlMinor, EUR)}</td><td className="amount">{item.returnPercent == null ? "Unavailable" : `${item.returnPercent}%`}</td></tr>)}</tbody></table></ExactData>
  </ChartSection>;
}
