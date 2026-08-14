import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { api } from "../api/client";
import type { Category, Dashboard } from "../api/types";
import { dashboardFixture } from "../features/dashboard/test-fixture";
import OverviewPage from "./OverviewPage";

const categories: Category[] = [
  { id: "food", name: "Food", sortOrder: 1, active: true, subcategories: [{ id: "cafes", categoryId: "food", name: "Cafes", sortOrder: 1, active: true }] },
  { id: "travel", name: "Travel", sortOrder: 2, active: true, subcategories: [{ id: "flights", categoryId: "travel", name: "Flights", sortOrder: 1, active: true }] },
  { id: "income", name: "Income", sortOrder: 3, active: true, subcategories: [{ id: "salary", categoryId: "income", name: "Salary", sortOrder: 1, active: true }] },
];

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Current query">{location.search}</output>;
}

function renderOverview(entry = "/") {
  return render(<MemoryRouter initialEntries={[entry]}><OverviewPage /><LocationProbe /></MemoryRouter>);
}

describe("OverviewPage analytical dashboard", () => {
  beforeEach(() => {
    vi.spyOn(api.taxonomy, "categories").mockResolvedValue(categories);
    vi.spyOn(api.dashboard, "get").mockResolvedValue(dashboardFixture);
  });

  it("uses local trailing-12-month defaults and writes them into the URL", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 7, 10, 9, 30));

    renderOverview();

    await waitFor(() => expect(api.dashboard.get).toHaveBeenCalledWith({
      dateFrom: "2025-08-10",
      dateTo: "2026-08-10",
      categoryIds: [],
      subcategoryIds: [],
    }));
    expect(await screen.findByLabelText("Current query")).toHaveTextContent("date_from=2025-08-10&date_to=2026-08-10");
    vi.useRealTimers();
  });

  it("round-trips repeated URL filters and clears subcategories outside changed categories", async () => {
    const user = userEvent.setup();
    renderOverview("/?date_from=2026-01-01&date_to=2026-08-10&category_id=food&category_id=travel&subcategory_id=cafes&subcategory_id=flights");

    await waitFor(() => expect(api.dashboard.get).toHaveBeenCalledWith(expect.objectContaining({
      categoryIds: ["food", "travel"],
      subcategoryIds: ["cafes", "flights"],
    })));
    await user.deselectOptions(screen.getByLabelText("Categories"), ["food"]);

    await waitFor(() => {
      const query = screen.getByLabelText("Current query").textContent ?? "";
      expect(query).toContain("category_id=travel");
      expect(query).toContain("subcategory_id=flights");
      expect(query).not.toContain("category_id=food");
      expect(query).not.toContain("subcategory_id=cafes");
    });
    await user.click(screen.getByRole("button", { name: "Show all categories" }));
    await waitFor(() => {
      const query = screen.getByLabelText("Current query").textContent ?? "";
      expect(query).not.toContain("category_id");
      expect(query).not.toContain("subcategory_id");
    });
  });

  it("shows exact KPIs, neutral prior copy, partial labels, and accessible chart tables", async () => {
    renderOverview("/?date_from=2025-08-10&date_to=2026-08-10");

    expect(await screen.findByText("€12,345.67")).toBeInTheDocument();
    expect(screen.getByText("Prior €10,000.00")).toBeInTheDocument();
    expect(screen.getByText(/€2,345.67 \/ 23.5% vs prior range/)).toBeInTheDocument();
    expect(screen.getByText(/No prior baseline vs prior range/)).toBeInTheDocument();
    expect(screen.getAllByText(/Partial/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("table").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("Exact cash-flow explorer data")).toBeInTheDocument();
    expect(screen.getByText("Exact cumulative cash-flow data")).toBeInTheDocument();
  });

  it("switches explorer fields and year-comparison measures against the loaded response", async () => {
    const user = userEvent.setup();
    renderOverview("/?date_from=2025-08-10&date_to=2026-08-10");
    await screen.findByText("Data through");
    const explorerDetails = screen.getByText("Exact cash-flow explorer data").closest("details");
    expect(explorerDetails).not.toBeNull();
    expect(within(explorerDetails!).getByText("€200.00")).toBeInTheDocument();

    await user.selectOptions(document.querySelector("#flow-measure")!, "income");
    expect(within(explorerDetails!).getByText("€1,000.00")).toBeInTheDocument();
    await user.selectOptions(document.querySelector("#flow-aggregation")!, "mean");
    expect(screen.getByLabelText("Rolling window")).toHaveValue("month");
    expect(within(explorerDetails!).getByText("€1,000.00")).toBeInTheDocument();
    expect(within(explorerDetails!).getAllByText("1").length).toBeGreaterThan(0);
    await user.selectOptions(document.querySelector("#flow-grain")!, "year");
    expect(within(explorerDetails!).getByText("€416.67")).toBeInTheDocument();

    const comparisonDetails = screen.getByText("Exact Jan-Dec comparison data").closest("details");
    expect(within(comparisonDetails!).getAllByText("€500.00").length).toBeGreaterThan(0);
    await user.selectOptions(document.querySelector("#comparison-measure")!, "net");
    expect(screen.getByRole("table", { name: "Net by calendar month and year" })).toBeInTheDocument();
  });

  it("switches composition measure and level against the loaded response", async () => {
    const user = userEvent.setup();
    renderOverview("/?date_from=2025-08-10&date_to=2026-08-10");

    const composition = await screen.findByRole("region", { name: "Composition" });
    const measureControl = within(composition).getByLabelText("Composition measure");
    const levelControl = within(composition).getByLabelText("Composition level");
    expect(within(measureControl).getByRole("button", { name: "Spending" })).toHaveAttribute("aria-pressed", "true");
    expect(within(composition).getByText("Exact spending composition data")).toBeInTheDocument();

    await user.click(within(measureControl).getByRole("button", { name: "Income" }));
    expect(within(composition).getByText("Exact income composition data")).toBeInTheDocument();
    const rankedIncome = within(composition).getByText("Ranked income").closest("details");
    expect(within(rankedIncome!).getByText("€2,200.00")).toBeInTheDocument();

    await user.click(within(levelControl).getByRole("button", { name: "Subcategory" }));
    expect(within(composition).getAllByText("Salary").length).toBeGreaterThan(0);

    await user.click(within(levelControl).getByRole("button", { name: "Category" }));
    await user.click(within(rankedIncome!).getByRole("button", { name: "Income" }));
    await waitFor(() => expect(screen.getByLabelText("Current query")).toHaveTextContent("category_id=income"));
  });

  it("rejects inverted dates inline without fetching the dashboard", async () => {
    renderOverview("/?date_from=2026-08-11&date_to=2026-08-10");

    expect(screen.getByText("From date must be on or before the to date.")).toBeInTheDocument();
    expect(screen.getByText("The dashboard was not requested because the date range is invalid.")).toBeInTheDocument();
    await waitFor(() => expect(api.taxonomy.categories).toHaveBeenCalled());
    expect(api.dashboard.get).not.toHaveBeenCalled();
  });

  it("preserves filtered URLs and blocks invalid requests when taxonomy is unavailable", async () => {
    vi.mocked(api.taxonomy.categories).mockRejectedValue(new Error("Taxonomy service unavailable"));
    renderOverview("/?date_from=2026-01-01&date_to=2026-08-10&category_id=food");

    expect(await screen.findByText(/Taxonomy filters are unavailable: Taxonomy service unavailable/)).toBeInTheDocument();
    expect(api.dashboard.get).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Current query")).toHaveTextContent("category_id=food");
  });

  it("retains controls and exposes retry when the analytical request fails", async () => {
    vi.mocked(api.dashboard.get).mockRejectedValue(new Error("Analytical service unavailable"));
    renderOverview("/?date_from=2026-01-01&date_to=2026-08-10");

    expect(await screen.findByText("Analytical service unavailable")).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toHaveValue("2026-01-01");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows the explanatory empty model while retaining zero-safe charts and tables", async () => {
    const user = userEvent.setup();
    const empty: Dashboard = {
      ...dashboardFixture,
      composition: {
        spending: { categoryMonthly: [], subcategoryMonthly: [], categoryRanked: [], subcategoryRanked: [] },
        income: { categoryMonthly: [], subcategoryMonthly: [], categoryRanked: [], subcategoryRanked: [] },
      },
      annual: [],
      cumulative: [],
      recent: [],
      quality: { transactionCount: 0, uncategorizedCount: 0, categoryOnlyCount: 0 },
    };
    vi.mocked(api.dashboard.get).mockResolvedValue(empty);
    renderOverview("/?date_from=2025-08-10&date_to=2026-08-10");

    expect(await screen.findByText(/No transactions match these filters/)).toBeInTheDocument();
    expect(screen.getByText("No ranked spending")).toBeInTheDocument();
    const compositionMeasure = screen.getByLabelText("Composition measure");
    await user.click(within(compositionMeasure).getByRole("button", { name: "Income" }));
    expect(screen.getByText("No income composition")).toBeInTheDocument();
    expect(screen.getByText("No ranked income")).toBeInTheDocument();
    expect(screen.queryByText("Recent entries")).not.toBeInTheDocument();
    expect(screen.getAllByRole("table").length).toBeGreaterThanOrEqual(4);
  });
});
