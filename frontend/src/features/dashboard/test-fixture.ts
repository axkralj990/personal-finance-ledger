import { mapDashboard } from "../../api/mappers";

const metric = (current: number, prior: number, percent: number | null) => ({
  current_minor: current,
  prior_minor: prior,
  delta_minor: current - prior,
  delta_percent: percent,
});

export const dashboardResponse = {
  meta: {
    date_from: "2025-08-10",
    date_to: "2026-08-10",
    prior_from: "2024-08-09",
    prior_to: "2025-08-09",
    data_from: "2025-08-12",
    data_to: "2026-08-09",
    generated_at: "2026-08-10T10:00:00Z",
    currency: "EUR",
    selected_category_ids: [],
    selected_subcategory_ids: [],
    partial_periods: {
      week: { first: true, last: true },
      month: { first: true, last: true },
      quarter: { first: true, last: true },
      year: { first: true, last: true },
    },
  },
  summary: {
    income: metric(1234567, 1000000, 23.4567),
    spending: metric(765432, 700000, 9.3474),
    net: metric(469135, 300000, 56.3783),
    monthly_spending_mean: metric(58879, 0, null),
  },
  series: {
    week: [{
      period_start: "2026-08-03", period_end: "2026-08-09", label: "03 Aug", partial: false, selected_days: 7,
      income_total_minor: 50000, spending_total_minor: 12000, net_total_minor: 38000,
    }],
    month: [
      {
        period_start: "2025-08-01", period_end: "2025-08-31", label: "Aug 2025", partial: true, selected_days: 22,
        income_total_minor: 100000, spending_total_minor: 80000, net_total_minor: 20000,
      },
      {
        period_start: "2025-09-01", period_end: "2025-09-30", label: "Sep 2025", partial: false, selected_days: 30,
        income_total_minor: 120000, spending_total_minor: 90000, net_total_minor: 30000,
      },
    ],
    quarter: [{
      period_start: "2025-07-01", period_end: "2025-09-30", label: "Q3 2025", partial: true, selected_days: 52,
      income_total_minor: 220000, spending_total_minor: 170000, net_total_minor: 50000,
    }],
    rolling_mean: {
      month: [
        {
          date: "2025-08-10", window_start: "2025-07-11", window_end: "2025-08-10",
          window_months: 1, income_mean_minor: 100000, spending_mean_minor: 80000, net_mean_minor: 20000,
        },
        {
          date: "2025-08-11", window_start: "2025-07-12", window_end: "2025-08-11",
          window_months: 1, income_mean_minor: 120000, spending_mean_minor: 90000, net_mean_minor: 30000,
        },
      ],
      quarter: [{
        date: "2025-08-10", window_start: "2025-05-11", window_end: "2025-08-10",
        window_months: 3, income_mean_minor: 73333, spending_mean_minor: 56667, net_mean_minor: 16667,
      }],
      year: [{
        date: "2025-08-10", window_start: "2024-08-11", window_end: "2025-08-10",
        window_months: 12, income_mean_minor: 41667, spending_mean_minor: 29167, net_mean_minor: 12500,
      }],
    },
  },
  composition: {
    category_monthly: [
      { period: "2025-08", taxonomy_id: "food", name: "Food", amount_minor: 50000, count: 8, partial: true },
      { period: "2025-08", taxonomy_id: "travel", name: "Travel", amount_minor: 30000, count: 2, partial: true },
      { period: "2025-09", taxonomy_id: "food", name: "Food", amount_minor: 60000, count: 9, partial: false },
      { period: "2025-09", taxonomy_id: "travel", name: "Travel", amount_minor: 30000, count: 1, partial: false },
    ],
    subcategory_monthly: [
      { period: "2025-08", taxonomy_id: "cafes", name: "Cafes", amount_minor: 50000, count: 8, partial: true },
      { period: "2025-08", taxonomy_id: "flights", name: "Flights", amount_minor: 30000, count: 2, partial: true },
    ],
    category_ranked: [
      { taxonomy_id: "food", name: "Food", amount_minor: 110000, count: 17, percentage: 64.7059 },
      { taxonomy_id: "travel", name: "Travel", amount_minor: 60000, count: 3, percentage: 35.2941 },
    ],
    subcategory_ranked: [
      { taxonomy_id: "cafes", name: "Cafes", amount_minor: 50000, count: 8, percentage: 62.5 },
      { taxonomy_id: "flights", name: "Flights", amount_minor: 30000, count: 2, percentage: 37.5 },
    ],
  },
  annual: [
    {
      year: 2025, partial: true,
      income_total_minor: 500000, spending_total_minor: 350000, net_total_minor: 150000,
      income_monthly_mean_minor: 41667, spending_monthly_mean_minor: 29167, net_monthly_mean_minor: 12500,
      months: Array.from({ length: 12 }, (_, index) => ({ month: index + 1, income_total_minor: index < 7 ? 0 : 100000, spending_total_minor: index < 7 ? 0 : 70000, net_total_minor: index < 7 ? 0 : 30000 })),
    },
    {
      year: 2026, partial: true,
      income_total_minor: 734567, spending_total_minor: 415432, net_total_minor: 319135,
      income_monthly_mean_minor: 61214, spending_monthly_mean_minor: 34619, net_monthly_mean_minor: 26595,
      months: Array.from({ length: 12 }, (_, index) => ({ month: index + 1, income_total_minor: index < 8 ? 90000 : 0, spending_total_minor: index < 8 ? 50000 : 0, net_total_minor: index < 8 ? 40000 : 0 })),
    },
  ],
  cumulative: [
    { date: "2025-08-10", net_minor: 2000, cumulative_minor: 2000 },
    { date: "2025-08-11", net_minor: -500, cumulative_minor: 1500 },
  ],
  recent: [{
    id: "transaction-1", date: "2026-08-09", description: "Rail ticket", amount_minor: -4200, kind: "EXPENSE",
    category_id: "travel", category_name: "Travel", subcategory_id: "trains", subcategory_name: "Trains",
    source_account_id: "account-1", source_account_name: "Main EUR",
  }],
  quality: { transaction_count: 42, uncategorized_count: 3, category_only_count: 2 },
};

export const dashboardFixture = mapDashboard(dashboardResponse);
