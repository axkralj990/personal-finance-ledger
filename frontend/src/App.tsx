import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";
import { AppShell } from "./components/AppShell";
import { LoadingState } from "./components/ui";

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const TransactionsPage = lazy(() => import("./pages/TransactionsPage"));
const ImportPage = lazy(() => import("./pages/ImportPage"));
const ImportReviewPage = lazy(() => import("./pages/ImportReviewPage"));
const ManualEntryPage = lazy(() => import("./pages/ManualEntryPage"));
const CategoriesPage = lazy(() => import("./pages/CategoriesPage"));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage"));

export default function App() {
  return (
    <Suspense fallback={<div className="route-loading"><LoadingState label="Opening ledger" /></div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="transactions" element={<TransactionsPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="imports/:id" element={<ImportReviewPage />} />
          <Route path="manual" element={<ManualEntryPage />} />
          <Route path="categories" element={<CategoriesPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
