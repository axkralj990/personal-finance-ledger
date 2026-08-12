import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import type { DashboardUrlFilters } from "../features/dashboard/filters";
import {
  CashFlowExplorer,
  CumulativeCashFlow,
  KpiStrip,
  SpendingComposition,
  YearComparison,
} from "../features/dashboard/DashboardSections";
import {
  dashboardDateError,
  getDefaultDashboardDates,
  readDashboardFilters,
  writeDashboardFilters,
} from "../features/dashboard/filters";
import { useResource } from "../hooks/use-resource";
import { ErrorState, Field, InlineNotice, LoadingState, PageHeader } from "../components/ui";
import { formatDate } from "../shared/format";

export default function OverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const defaults = getDefaultDashboardDates();
  const searchKey = searchParams.toString();
  const filters = readDashboardFilters(searchParams);
  const dateError = dashboardDateError(filters);

  useEffect(() => {
    if (searchParams.has("date_from") && searchParams.has("date_to")) return;
    const next = new URLSearchParams(searchParams);
    if (!next.has("date_from")) next.set("date_from", defaults.dateFrom);
    if (!next.has("date_to")) next.set("date_to", defaults.dateTo);
    setSearchParams(next, { replace: true });
  }, [defaults.dateFrom, defaults.dateTo, searchKey, searchParams, setSearchParams]);

  const taxonomy = useResource(() => api.taxonomy.categories(), "dashboard-taxonomy");
  const hasTaxonomyFilters = filters.categoryIds.length > 0 || filters.subcategoryIds.length > 0;
  const taxonomyBlocksDashboard = hasTaxonomyFilters
    && (taxonomy.loading || Boolean(taxonomy.error) || taxonomy.data === null);
  const dashboard = useResource(
    () => dateError || taxonomyBlocksDashboard
      ? Promise.resolve(null)
      : api.dashboard.get({
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        categoryIds: filters.categoryIds,
        subcategoryIds: filters.subcategoryIds,
      }),
    `dashboard:${filters.dateFrom}:${filters.dateTo}:${filters.categoryIds.join(",")}:${filters.subcategoryIds.join(",")}:${dateError ?? "valid"}:${taxonomyBlocksDashboard ? "taxonomy-blocked" : "taxonomy-ready"}`,
  );

  const categories = taxonomy.data ?? [];
  const selectedCategories = new Set(filters.categoryIds);
  const availableSubcategories = categories.flatMap((category) => category.subcategories)
    .filter((subcategory) => selectedCategories.size === 0 || selectedCategories.has(subcategory.categoryId));
  const realCategoryIds = new Set(categories.map((category) => category.id));

  useEffect(() => {
    if (!taxonomy.data || !hasTaxonomyFilters) return;
    const validCategoryIds = new Set(taxonomy.data.map((category) => category.id));
    const categoryIds = filters.categoryIds.filter((id) => validCategoryIds.has(id));
    const selectedCategoryIds = new Set(categoryIds);
    const validSubcategoryIds = new Set(
      taxonomy.data
        .filter((category) => selectedCategoryIds.size === 0 || selectedCategoryIds.has(category.id))
        .flatMap((category) => category.subcategories.map((subcategory) => subcategory.id)),
    );
    const subcategoryIds = filters.subcategoryIds.filter((id) => validSubcategoryIds.has(id));
    if (
      categoryIds.length !== filters.categoryIds.length
      || subcategoryIds.length !== filters.subcategoryIds.length
    ) {
      setSearchParams(writeDashboardFilters({ ...filters, categoryIds, subcategoryIds }), {
        replace: true,
      });
    }
  }, [filters, hasTaxonomyFilters, searchKey, setSearchParams, taxonomy.data]);

  const updateFilters = (next: DashboardUrlFilters) => setSearchParams(writeDashboardFilters(next));
  const updateCategories = (categoryIds: string[]) => {
    const compatibleSubcategoryIds = new Set(categories
      .filter((category) => categoryIds.length === 0 || categoryIds.includes(category.id))
      .flatMap((category) => category.subcategories.map((subcategory) => subcategory.id)));
    updateFilters({
      ...filters,
      categoryIds,
      subcategoryIds: filters.subcategoryIds.filter((id) => compatibleSubcategoryIds.has(id)),
    });
  };
  const data = dashboard.data;
  const coverage = data?.meta.dataFrom && data.meta.dataTo
    ? `${formatDate(data.meta.dataFrom)} to ${formatDate(data.meta.dataTo)}`
    : "No matching ledger coverage";

  return (
    <div className="dashboard-page">
      <PageHeader
        eyebrow="Overview / EUR analytical ledger"
        title="The shape of your ledger"
        description={`Selected range ${formatDate(filters.dateFrom)} to ${formatDate(filters.dateTo)}. Data coverage: ${coverage}.`}
      />

      <section className="dashboard-filter-rail" aria-label="Dashboard filters">
        <div className="filter-rail-intro"><span>Range and taxonomy</span><strong>EUR fixed</strong><button type="button" className="filter-rail-reset" disabled={!filters.categoryIds.length && !filters.subcategoryIds.length} onClick={() => updateFilters({ ...filters, categoryIds: [], subcategoryIds: [] })}>Show all categories</button></div>
        <Field label="From" htmlFor="dashboard-from" error={dateError}>
          {(props) => <input {...props} id="dashboard-from" type="date" value={filters.dateFrom} onChange={(event) => updateFilters({ ...filters, dateFrom: event.target.value })} />}
        </Field>
        <Field label="To" htmlFor="dashboard-to">
          <input id="dashboard-to" type="date" value={filters.dateTo} aria-invalid={Boolean(dateError)} aria-describedby={dateError ? "dashboard-from-error" : undefined} onChange={(event) => updateFilters({ ...filters, dateTo: event.target.value })} />
        </Field>
        <Field label="Categories" htmlFor="dashboard-categories" hint="Command/Ctrl-click to select several">
          {(props) => <select
            {...props}
            id="dashboard-categories"
            multiple
            value={filters.categoryIds}
            disabled={taxonomy.loading || Boolean(taxonomy.error)}
            onChange={(event) => updateCategories([...event.target.selectedOptions].map((option) => option.value))}
          >
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>}
        </Field>
        <Field label="Subcategories" htmlFor="dashboard-subcategories" hint={filters.categoryIds.length ? "Limited to selected categories" : "All categories available"}>
          {(props) => <><select
              {...props}
              id="dashboard-subcategories"
              multiple
              value={filters.subcategoryIds}
              disabled={taxonomy.loading || Boolean(taxonomy.error)}
              onChange={(event) => updateFilters({ ...filters, subcategoryIds: [...event.target.selectedOptions].map((option) => option.value) })}
            >
              {availableSubcategories.map((subcategory) => <option key={subcategory.id} value={subcategory.id}>{subcategory.name}</option>)}
            </select><button type="button" className="filter-clear" disabled={!filters.subcategoryIds.length} onClick={() => updateFilters({ ...filters, subcategoryIds: [] })}>Clear subcategories</button></>}
        </Field>
      </section>

      {taxonomy.error && <InlineNotice tone="bad">Taxonomy filters are unavailable: {taxonomy.error.message} <button className="button ghost" type="button" onClick={taxonomy.reload}>Retry taxonomy</button></InlineNotice>}

      {dateError ? <InlineNotice tone="bad">The dashboard was not requested because the date range is invalid.</InlineNotice>
        : dashboard.loading ? <LoadingState label="Reconciling the analytical ledger" />
        : dashboard.error ? <ErrorState error={dashboard.error} retry={dashboard.reload} />
        : !data ? null
        : <>
          <div className="dashboard-coverage" aria-label="Dashboard data quality">
            <span>Data through <strong>{data.meta.dataTo ? formatDate(data.meta.dataTo) : "no matching date"}</strong></span>
            <span className="num">{data.quality.transactionCount} matching / {data.quality.uncategorizedCount} uncategorized / {data.quality.categoryOnlyCount} category-only</span>
          </div>
          {data.quality.transactionCount === 0 && <InlineNotice>No transactions match these filters. Zero-filled analytical views remain visible for the selected calendar range.</InlineNotice>}
          <KpiStrip data={data} />
          <CashFlowExplorer data={data} />
          <SpendingComposition
            data={data}
            realCategoryIds={realCategoryIds}
            onCategoryFilter={(id) => updateCategories([id])}
          />
          <YearComparison data={data} />
          <CumulativeCashFlow data={data} />
        </>}
    </div>
  );
}
