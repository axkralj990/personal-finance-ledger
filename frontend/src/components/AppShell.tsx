import { useEffect, useRef } from "react";
import { BookOpen, BriefcaseBusiness, CircleDollarSign, FileInput, FolderTree, LayoutDashboard, PenLine, Wifi, WifiOff } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router";
import { api } from "../api/client";
import { useResource } from "../hooks/use-resource";

const navItems = [
  { to: "/", label: "Overview", mobileLabel: "Home", icon: LayoutDashboard, end: true },
  { to: "/transactions", label: "Transactions", mobileLabel: "Ledger", icon: BookOpen },
  { to: "/portfolio", label: "Portfolio", mobileLabel: "Portfolio", icon: BriefcaseBusiness },
  { to: "/import", label: "Import", mobileLabel: "Import", icon: FileInput },
  { to: "/manual", label: "Manual entry", mobileLabel: "Manual", icon: PenLine },
  { to: "/categories", label: "Categories", mobileLabel: "Labels", icon: FolderTree },
];

export function AppShell() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const health = useResource(() => api.health(), "service-health");

  useEffect(() => {
    const heading = mainRef.current?.querySelector<HTMLElement>("[data-page-heading]");
    heading?.focus();
  }, [location.pathname]);

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="side-nav" aria-label="Primary navigation">
        <div className="brand-mark">
          <CircleDollarSign aria-hidden="true" />
          <div><strong>Ledger Studio</strong><span>Personal books</span></div>
        </div>
        <nav>
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              <Icon aria-hidden="true" /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="service-state" title={health.error ? health.error.message : "Ledger service connection"}>
          {health.data?.status === "ok" || health.data?.status === "healthy" ? <Wifi aria-hidden="true" /> : <WifiOff aria-hidden="true" />}
          <span>{health.loading ? "Checking service" : health.error ? "Service offline" : "Service connected"}</span>
        </div>
      </aside>
      <main id="main-content" ref={mainRef} className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
      <nav className="bottom-nav" aria-label="Primary navigation">
        {navItems.map(({ to, mobileLabel, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? "active" : ""}>
            <Icon aria-hidden="true" /><span>{mobileLabel}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
