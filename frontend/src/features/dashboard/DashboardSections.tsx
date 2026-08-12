import { useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  Dashboard,
  DashboardAnnualMonth,
  DashboardMetricComparison,
  DashboardRollingMeanPoint,
  DashboardSeriesPoint,
} from "../../api/types";
import { EmptyState, Field } from "../../components/ui";
import { formatDate, formatMoney } from "../../shared/format";
import { buildCompositionChartData, LEDGER_PALETTE } from "./composition";

const EUR = "EUR";
const RULE = "#d8d1c2";
const MUTED = "#686a61";
const INCOME_COLOR = "#315b45";
const SPENDING_COLOR = "#a44d32";
const NET_COLOR = "#315f6b";
const YEAR_COLORS = LEDGER_PALETTE;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type FlowMeasure = "income" | "spending" | "net";
type FlowAggregation = "total" | "mean";
type TotalGrain = "week" | "month" | "quarter";
type MeanWindow = "month" | "quarter" | "year";

interface FlowChartPoint {
  key: string;
  label: string;
  rangeStart: string;
  rangeEnd: string;
  partial: boolean;
  selectedDays: number | null;
  windowMonths: number | null;
  valueMinor: number | null;
}

const MEASURE_LABELS: Record<FlowMeasure, string> = { income: "Income", spending: "Spending", net: "Net" };
const MEASURE_COLORS: Record<FlowMeasure, string> = { income: INCOME_COLOR, spending: SPENDING_COLOR, net: NET_COLOR };
const TOTAL_FIELDS: Record<FlowMeasure, keyof DashboardSeriesPoint> = { income: "incomeTotalMinor", spending: "spendingTotalMinor", net: "netTotalMinor" };
const MEAN_FIELDS: Record<FlowMeasure, keyof DashboardRollingMeanPoint> = { income: "incomeMeanMinor", spending: "spendingMeanMinor", net: "netMeanMinor" };
const WINDOW_LABELS: Record<MeanWindow, string> = { month: "trailing calendar month", quarter: "trailing 3 calendar months", year: "trailing 12 calendar months" };

function euroAxis(value: number): string {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: EUR,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value / 100);
}

function MoneyTooltip() {
  return (
    <Tooltip
      formatter={(value, name) => [formatMoney(Number(value), EUR), String(name)]}
      contentStyle={{ background: "#fbf8f0", border: "1px solid #b9b1a3", borderRadius: 0 }}
    />
  );
}

function SectionHeading({ id, number, title, note, children }: { id: string; number: string; title: string; note: string; children?: ReactNode }) {
  return (
    <header className="dashboard-section-heading">
      <span className="dashboard-section-number" aria-hidden="true">{number}</span>
      <div><h2 id={id}>{title}</h2><p>{note}</p></div>
      {children && <div className="dashboard-controls">{children}</div>}
    </header>
  );
}

function DataDisclosure({ label, children }: { label: string; children: ReactNode }) {
  return <details className="dashboard-data"><summary>{label}</summary><div className="dashboard-table-scroll">{children}</div></details>;
}

function PartialReferenceLines({ points }: { points: { label: string; partial: boolean }[] }) {
  return points.filter((point) => point.partial).map((point) => (
    <ReferenceLine
      key={point.label}
      x={point.label}
      stroke="#87533d"
      strokeDasharray="3 3"
      label={{ value: "Partial", position: "insideTop", fill: "#87533d", fontSize: 10 }}
    />
  ));
}

export function KpiStrip({ data }: { data: Dashboard }) {
  const metrics: { label: string; value: DashboardMetricComparison; className?: string }[] = [
    { label: "Income", value: data.summary.income },
    { label: "Spending", value: data.summary.spending },
    { label: "Net", value: data.summary.net, className: data.summary.net.currentMinor >= 0 ? "net-positive" : "net-negative" },
    { label: "Monthly spending mean", value: data.summary.monthlySpendingMean },
  ];
  const partialMonth = data.meta.partialPeriods.month.first || data.meta.partialPeriods.month.last;
  return (
    <section className="dashboard-kpis" aria-label="Selected range summary">
      {metrics.map(({ label, value, className }) => (
        <article className={`dashboard-kpi ${className ?? ""}`} key={label}>
          <span>{label}</span>
          <strong>{formatMoney(value.currentMinor, EUR)}</strong>
          <p className="num">Prior {formatMoney(value.priorMinor, EUR)}</p>
          <p className="dashboard-kpi-change num">
            {value.deltaMinor > 0 ? "+" : ""}{formatMoney(value.deltaMinor, EUR)} / {value.deltaPercent == null ? "No prior baseline" : `${value.deltaPercent.toFixed(1)}%`} vs prior range
          </p>
        </article>
      ))}
      <p className="dashboard-range-note">
        Selected {formatDate(data.meta.dateFrom)} to {formatDate(data.meta.dateTo)}. Prior {formatDate(data.meta.priorFrom)} to {formatDate(data.meta.priorTo)}.
        {partialMonth ? " Boundary months are partial." : " Calendar-month boundaries are complete."}
      </p>
    </section>
  );
}

export function CashFlowExplorer({ data }: { data: Dashboard }) {
  const [measure, setMeasure] = useState<FlowMeasure>("net");
  const [aggregation, setAggregation] = useState<FlowAggregation>("total");
  const [totalGrain, setTotalGrain] = useState<TotalGrain>("month");
  const [meanWindow, setMeanWindow] = useState<MeanWindow>("month");
  const totalPoints: FlowChartPoint[] = data.series[totalGrain].map((point) => ({
    key: point.periodStart,
    label: point.label,
    rangeStart: point.periodStart,
    rangeEnd: point.periodEnd,
    partial: point.partial,
    selectedDays: point.selectedDays,
    windowMonths: null,
    valueMinor: Number(point[TOTAL_FIELDS[measure]]),
  }));
  const meanPoints: FlowChartPoint[] = data.series.rollingMean[meanWindow].map((point) => {
    const value = point[MEAN_FIELDS[measure]];
    return {
      key: point.date,
      label: formatDate(point.date),
      rangeStart: point.windowStart,
      rangeEnd: point.windowEnd,
      partial: false,
      selectedDays: null,
      windowMonths: point.windowMonths,
      valueMinor: typeof value === "number" ? value : null,
    };
  });
  const chartData: FlowChartPoint[] = aggregation === "total" ? totalPoints : meanPoints;
  const valueLabel = `${MEASURE_LABELS[measure]} ${aggregation === "total" ? "total" : "monthly mean"}`;
  const note = aggregation === "total"
    ? "Zero-filled calendar periods."
    : `Daily points dividing each trailing window total by ${meanWindow === "month" ? "1 month" : meanWindow === "quarter" ? "3 months" : "12 months"}.`;
  return (
    <section className="dashboard-section" aria-labelledby="cash-flow-title">
      <SectionHeading id="cash-flow-title" number="01" title="Cash-flow explorer" note={note}>
        <Field label="Measure" htmlFor="flow-measure"><select id="flow-measure" value={measure} onChange={(event) => setMeasure(event.target.value as FlowMeasure)}><option value="income">Income</option><option value="spending">Spending</option><option value="net">Net</option></select></Field>
        <Field label="Aggregation" htmlFor="flow-aggregation"><select id="flow-aggregation" value={aggregation} onChange={(event) => setAggregation(event.target.value as FlowAggregation)}><option value="total">Total</option><option value="mean">Rolling mean</option></select></Field>
        <Field label={aggregation === "total" ? "Grain" : "Rolling window"} htmlFor="flow-grain"><select id="flow-grain" value={aggregation === "total" ? totalGrain : meanWindow} onChange={(event) => aggregation === "total" ? setTotalGrain(event.target.value as TotalGrain) : setMeanWindow(event.target.value as MeanWindow)}>{aggregation === "total" ? <><option value="week">Week</option><option value="month">Month</option><option value="quarter">Quarter</option></> : <><option value="month">Month</option><option value="quarter">Quarter</option><option value="year">Year</option></>}</select></Field>
      </SectionHeading>
      <p className="chart-summary">{aggregation === "total" ? `Showing ${valueLabel.toLowerCase()} in EUR by ${totalGrain}. Dashed vertical markers identify partial periods.` : `Showing ${valueLabel.toLowerCase()} in EUR over the ${WINDOW_LABELS[meanWindow]}.`}</p>
      <div className="dashboard-chart dashboard-chart-large">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 26, right: 18, left: 8, bottom: 8 }} accessibilityLayer>
            <CartesianGrid stroke={RULE} strokeDasharray="2 5" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: MUTED, fontSize: 11 }} tickLine={false} axisLine={{ stroke: RULE }} />
            <YAxis tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 11 }} tickLine={false} axisLine={false} width={70} />
            <MoneyTooltip />
            {measure === "net" && <ReferenceLine y={0} stroke="#272923" label={{ value: "Zero", fill: MUTED, fontSize: 10 }} />}
            {aggregation === "total" && <PartialReferenceLines points={chartData} />}
            <Line name={valueLabel} type="monotone" dataKey="valueMinor" stroke={MEASURE_COLORS[measure]} strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataDisclosure label="Exact cash-flow explorer data">
        {aggregation === "total"
          ? <table className="data-table"><caption className="sr-only">Exact {valueLabel.toLowerCase()} data</caption><thead><tr><th>Period</th><th>Date range</th><th>Days</th><th>Boundary</th><th className="amount">{valueLabel}</th></tr></thead><tbody>{chartData.map((point) => <tr key={point.key}><td>{point.label}</td><td>{formatDate(point.rangeStart)} to {formatDate(point.rangeEnd)}</td><td className="num">{point.selectedDays}</td><td>{point.partial ? "Partial" : "Complete"}</td><td className="amount">{formatMoney(point.valueMinor, EUR)}</td></tr>)}</tbody></table>
          : <table className="data-table"><caption className="sr-only">Exact {valueLabel.toLowerCase()} data</caption><thead><tr><th>Date</th><th>Rolling window</th><th>Months</th><th className="amount">{valueLabel}</th></tr></thead><tbody>{chartData.map((point) => <tr key={point.key}><td>{point.label}</td><td>{formatDate(point.rangeStart)} to {formatDate(point.rangeEnd)}</td><td className="num">{point.windowMonths}</td><td className="amount">{formatMoney(point.valueMinor, EUR)}</td></tr>)}</tbody></table>}
      </DataDisclosure>
    </section>
  );
}

export function SpendingComposition({ data, realCategoryIds, onCategoryFilter }: { data: Dashboard; realCategoryIds: Set<string>; onCategoryFilter: (id: string) => void }) {
  const [level, setLevel] = useState<"category" | "subcategory">("category");
  const monthly = level === "category" ? data.composition.categoryMonthly : data.composition.subcategoryMonthly;
  const ranked = level === "category" ? data.composition.categoryRanked : data.composition.subcategoryRanked;
  const chart = buildCompositionChartData(
    monthly,
    ranked,
    8,
    data.series.month.map((point) => ({ label: point.label, partial: point.partial })),
  );
  return (
    <section className="dashboard-section" aria-labelledby="composition-title">
      <SectionHeading id="composition-title" number="02" title="Spending composition" note="Monthly spending only. Top eight taxonomy lines remain stable across the chart.">
        <div className="dashboard-toggle" aria-label="Composition level">
          <button type="button" aria-pressed={level === "category"} onClick={() => setLevel("category")}>Category</button>
          <button type="button" aria-pressed={level === "subcategory"} onClick={() => setLevel("subcategory")}>Subcategory</button>
        </div>
      </SectionHeading>
      {chart.columns.length ? <>
        <div className="dashboard-chart dashboard-chart-large">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart.rows} margin={{ top: 25, right: 12, left: 5, bottom: 8 }} accessibilityLayer>
              <CartesianGrid stroke={RULE} strokeDasharray="2 5" vertical={false} />
              <XAxis dataKey="period" tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} axisLine={{ stroke: RULE }} />
              <YAxis tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} axisLine={false} width={66} />
              <MoneyTooltip />
              <PartialReferenceLines points={chart.rows.map((row) => ({ label: String(row.period), partial: Boolean(row.partial) }))} />
              {chart.columns.map((column) => <Bar key={column.taxonomyId} name={column.name} dataKey={column.key} stackId="spending" fill={column.color} isAnimationActive={false} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-key" aria-label="Spending composition legend">{chart.columns.map((column) => <span key={column.taxonomyId}><i style={{ background: column.color }} aria-hidden="true" />{column.name}</span>)}</div>
      </> : <EmptyState title="No spending composition" description="No expense or fee rows match the selected range and taxonomy." />}
      <DataDisclosure label="Ranked spending">
        {ranked.length ? <table className="data-table"><caption className="sr-only">Ranked spending by {level}</caption><thead><tr><th>Rank</th><th>{level === "category" ? "Category" : "Subcategory"}</th><th>Entries</th><th className="amount">Spending</th><th className="amount">Share</th></tr></thead><tbody>{ranked.map((item, index) => { const canFilter = level === "category" && realCategoryIds.has(item.taxonomyId); return <tr key={item.taxonomyId}><td className="num">{index + 1}</td><td>{canFilter ? <button className="table-link" type="button" onClick={() => onCategoryFilter(item.taxonomyId)}>{item.name}</button> : item.name}</td><td className="num">{item.count}</td><td className="amount">{formatMoney(item.amountMinor, EUR)}</td><td className="amount">{item.percentage.toFixed(1)}%</td></tr>; })}</tbody></table> : <EmptyState title="No ranked spending" description="No ranked spending matches the selected filters." />}
      </DataDisclosure>
      <DataDisclosure label="Exact spending composition data">
        <table className="data-table"><caption className="sr-only">Monthly spending composition by {level}</caption><thead><tr><th>Period</th>{chart.columns.map((column) => <th className="amount" key={column.taxonomyId}>{column.name}</th>)}<th>Boundary</th></tr></thead><tbody>{chart.rows.map((row) => <tr key={String(row.period)}><td>{String(row.period)}</td>{chart.columns.map((column) => <td className="amount" key={column.taxonomyId}>{formatMoney(Number(row[column.key]), EUR)}</td>)}<td>{row.partial ? "Partial" : "Complete"}</td></tr>)}</tbody></table>
      </DataDisclosure>
    </section>
  );
}

function annualMonthValue(month: DashboardAnnualMonth | undefined, measure: FlowMeasure): number {
  if (!month) return 0;
  if (measure === "income") return month.incomeTotalMinor;
  if (measure === "spending") return month.spendingTotalMinor;
  return month.netTotalMinor;
}

export function YearComparison({ data }: { data: Dashboard }) {
  const [comparisonMeasure, setComparisonMeasure] = useState<FlowMeasure>("spending");
  const comparisonRows: ({ month: string } & Record<string, string | number>)[] = MONTHS.map((month, index) => ({
    month,
    ...Object.fromEntries(data.annual.map((year) => [String(year.year), annualMonthValue(year.months[index], comparisonMeasure)])),
  }));
  return (
    <section className="dashboard-section" aria-labelledby="year-comparison-title">
      <SectionHeading id="year-comparison-title" number="03" title="Jan-Dec year comparison" note="Each month groups consecutive years side by side for direct comparison.">
        <Field label="Measure" htmlFor="comparison-measure"><select id="comparison-measure" value={comparisonMeasure} onChange={(event) => setComparisonMeasure(event.target.value as FlowMeasure)}><option value="income">Income</option><option value="spending">Spending</option><option value="net">Net</option></select></Field>
      </SectionHeading>
      <div className="dashboard-chart dashboard-chart-large">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={comparisonRows} margin={{ top: 20, right: 14, left: 8, bottom: 8 }} barCategoryGap="18%" barGap={2} accessibilityLayer>
            <CartesianGrid stroke={RULE} strokeDasharray="2 5" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: MUTED, fontSize: 11 }} tickLine={false} axisLine={{ stroke: RULE }} />
            <YAxis tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 11 }} tickLine={false} axisLine={false} width={70} />
            <MoneyTooltip /><ReferenceLine y={0} stroke="#272923" label={{ value: "Zero", fill: MUTED, fontSize: 10 }} />
            <Legend formatter={(value) => { const year = data.annual.find((item) => String(item.year) === String(value)); return year?.partial ? `${value} (partial)` : value; }} />
            {data.annual.map((year, index) => <Bar key={year.year} name={String(year.year)} dataKey={String(year.year)} fill={YEAR_COLORS[index % YEAR_COLORS.length]} fillOpacity={year.partial ? .68 : 1} stroke={YEAR_COLORS[index % YEAR_COLORS.length]} strokeWidth={1} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <DataDisclosure label="Exact Jan-Dec comparison data">
        <table className="data-table"><caption className="sr-only">{MEASURE_LABELS[comparisonMeasure]} by calendar month and year</caption><thead><tr><th>Month</th>{data.annual.map((year) => <th className="amount" key={year.year}>{year.year}{year.partial ? " partial" : ""}</th>)}</tr></thead><tbody>{comparisonRows.map((row) => <tr key={row.month}><td>{row.month}</td>{data.annual.map((year) => <td className="amount" key={year.year}>{formatMoney(Number(row[String(year.year)]), EUR)}</td>)}</tr>)}</tbody></table>
      </DataDisclosure>
    </section>
  );
}

export function CumulativeCashFlow({ data }: { data: Dashboard }) {
  return (
    <section className="dashboard-section" aria-labelledby="cumulative-title">
      <SectionHeading id="cumulative-title" number="04" title="Cumulative cash flow" note="Selected-range cash flow starting at zero. This is movement, not an account balance." />
      <p className="chart-summary">Daily signed net accumulated only within the selected range.</p>
      <div className="dashboard-chart dashboard-chart-large">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.cumulative} margin={{ top: 12, right: 14, left: 8, bottom: 8 }} accessibilityLayer>
            <CartesianGrid stroke={RULE} strokeDasharray="2 5" vertical={false} />
            <XAxis dataKey="date" tickFormatter={(value) => formatDate(String(value)).replace(/\s\d{4}$/, "")} tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} axisLine={{ stroke: RULE }} minTickGap={32} />
            <YAxis tickFormatter={euroAxis} tick={{ fill: MUTED, fontSize: 10 }} tickLine={false} axisLine={false} width={70} />
            <MoneyTooltip /><ReferenceLine y={0} stroke="#272923" label={{ value: "Zero cash flow", fill: MUTED, fontSize: 10 }} />
            <Line name="Cumulative cash flow" type="monotone" dataKey="cumulativeMinor" stroke={NET_COLOR} strokeWidth={2.25} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataDisclosure label="Exact cumulative cash-flow data">
        <table className="data-table"><caption className="sr-only">Daily selected-range cumulative cash flow</caption><thead><tr><th>Date</th><th className="amount">Daily net</th><th className="amount">Cumulative cash flow</th></tr></thead><tbody>{data.cumulative.map((point) => <tr key={point.date}><td>{formatDate(point.date)}</td><td className="amount">{formatMoney(point.netMinor, EUR)}</td><td className="amount">{formatMoney(point.cumulativeMinor, EUR)}</td></tr>)}</tbody></table>
      </DataDisclosure>
    </section>
  );
}
