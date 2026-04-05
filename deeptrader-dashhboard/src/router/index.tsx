import { createBrowserRouter, redirect } from "react-router-dom";
import DashboardLayout from "../pages/dashboard/layout";
import OverviewPage from "../pages/dashboard/overview";
import FleetOverviewPage from "../pages/dashboard/fleet-overview";
import DashboardHomePage from "../pages/dashboard/home";
import TradingOpsPage from "../pages/dashboard/trading-ops";
import SignalLabPage from "../pages/dashboard/signal-lab";
import BotManagementPage from "../pages/dashboard/bot-management";
import DocsPage from "../pages/dashboard/docs";

// Settings pages
import SettingsHomePage from "../pages/dashboard/settings/index";
import SettingsAccountPage from "../pages/dashboard/settings/account";
import SettingsTradingPage from "../pages/dashboard/settings/trading";
import SettingsRiskPage from "../pages/dashboard/settings/risk";
import SettingsExchangesPage from "../pages/dashboard/settings/exchanges";
import SettingsNotificationsPage from "../pages/dashboard/settings/notifications";
import SettingsDataPage from "../pages/dashboard/settings/data";
import SettingsSecurityPage from "../pages/dashboard/settings/security";
import SettingsBillingPage from "../pages/dashboard/settings/billing";
import SettingsSystemHealthPage from "../pages/dashboard/settings/system-health";
import LiveTradingPage from "../pages/dashboard/live-trading";
import TradeHistoryPage from "../pages/dashboard/trade-history-v2";
import PositionsRiskPage from "../pages/dashboard/positions-risk";
import PortfolioAllocatorPage from "../pages/dashboard/portfolio-allocator";
import MarketContextPage from "../pages/dashboard/market-context";
import SystemHealthPage from "../pages/dashboard/system-health";
import ProfileEditorPage from "../pages/dashboard/profile-editor";
import StrategyConfigPage from "../pages/dashboard/strategy-config";
import SignalCustomizationPage from "../pages/dashboard/signal-customization";
import TCAPage from "../pages/dashboard/tca";
import RiskMetricsPage from "../pages/dashboard/risk-metrics";
import PromotionsPage from "../pages/dashboard/promotions";
import AuditLogPage from "../pages/dashboard/audit";
// ReplayPage removed - redundant with ReplayStudioPage at /analysis/replay
import DataQualityPage from "../pages/dashboard/data-quality";
import PortfolioPage from "../pages/dashboard/portfolio";
import ReportingPage from "../pages/dashboard/reporting";
import ActiveBotPage from "../pages/dashboard/active-bot";
import StrategiesPage from "../pages/dashboard/strategies";
import ExecutionPage from "../pages/dashboard/execution";
import HistoryPage from "../pages/dashboard/history";
import OrdersPage from "../pages/dashboard/orders";
import SignalsPage from "../pages/dashboard/signals";
import ProfilesPage from "../pages/dashboard/profiles";
import BacktestingPage from "../pages/dashboard/backtesting";
import RiskLimitsPage from "../pages/dashboard/risk-limits";
import RiskExposurePage from "../pages/dashboard/risk-exposure";
import RiskIncidentsPage from "../pages/dashboard/risk-incidents";
import ReplayStudioPage from "../pages/dashboard/replay-studio";
import PipelineHealthPage from "../pages/dashboard/pipeline-health";
import ProtectedRoute from "../routes/protected-route";
import BotOperatePage from "../pages/dashboard/bot/operate";
import BotPositionsPage from "../pages/dashboard/bot/positions";
import BotDecisionsPage from "../pages/dashboard/bot/decisions";
import BotHistoryPage from "../pages/dashboard/bot/history";
import ExchangeAccountsPage from "../pages/dashboard/exchange-accounts";
import LandingPage from "../pages/landing";
import SignInPage from "../pages/auth/sign-in";
import SignUpPage from "../pages/auth/sign-up";
import ViewerDashboardPage from "../pages/viewer";

// Trading Pipeline Integration pages
// Feature: trading-pipeline-integration
// **Validates: Requirements 4.5, 9.3**
import ShadowComparisonPage from "../pages/dashboard/shadow-comparison";
import ConfigManagementPage from "../pages/dashboard/config-management";
import ReplayValidationPage from "../pages/dashboard/replay-validation";
import MetricsComparisonPage from "../pages/dashboard/metrics-comparison";
import ModelTrainingPage from "../pages/dashboard/model-training";
import RuntimeConfigPage from "../pages/dashboard/runtime-config";

// Landing page URL - all auth redirects go here (detect dynamically)
function getLandingUrl(): string {
  if (import.meta.env.VITE_LANDING_URL) {
    return import.meta.env.VITE_LANDING_URL;
  }
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    const port = window.location.port;
    const portSuffix = port ? `:${port}` : "";
    if (hostname.includes('quantgambit.local')) {
      return `${protocol}//quantgambit.local${portSuffix}`;
    }

    if (hostname.endsWith('quantgambit.com')) {
      return `${protocol}//quantgambit.com`;
    }
  }
  return "http://localhost:3000";
}
const LANDING_URL = getLandingUrl();

function isDashboardHost(): boolean {
  if (typeof window === "undefined") return true;
  const hostname = window.location.hostname.toLowerCase();
  if (hostname === "localhost" || hostname === "127.0.0.1") return true;
  if (hostname.startsWith("dashboard.")) return true;
  // Local nginx style: dashboard.quantgambit.local
  if (hostname === "dashboard.quantgambit.local") return true;
  return false;
}

// Helper to do external redirects (can't use React Router redirect for external URLs)
function externalRedirect(url: string) {
  window.location.href = url;
  return null;
}

// Redirect component for external URLs
function ExternalRedirect({ to }: { to: string }) {
  externalRedirect(to);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  );
}

export const router = createBrowserRouter([
  ...(isDashboardHost()
    ? [
        {
          // Sign-in redirects to landing page sign-in
          path: "/auth/sign-in",
          element: <ExternalRedirect to={`${LANDING_URL}/sign-in`} />,
        },
        {
          // Sign-up redirects to landing page request access
          path: "/auth/sign-up",
          element: <ExternalRedirect to={`${LANDING_URL}/request-access`} />,
        },
        {
          // Legacy /dashboard path redirects to root
          path: "/dashboard/*",
          loader: ({ params }) => redirect(`/${params["*"] || ""}`),
        },
        {
          path: "/viewer",
          element: (
            <ProtectedRoute>
              <ViewerDashboardPage />
            </ProtectedRoute>
          ),
        },
        {
          // All dashboard routes are now at root level
          path: "/",
          element: (
            <ProtectedRoute>
              <DashboardLayout />
            </ProtectedRoute>
          ),
          children: [
      // Trading - What's happening right now
      // Overview is default; add fleet route explicitly for fleet-wide view
      { index: true, element: <OverviewPage /> },
      { path: "fleet", element: <FleetOverviewPage /> },
      { path: "live", element: <LiveTradingPage /> },
      { path: "orders", element: <OrdersPage /> },
      { path: "positions", element: <PositionsRiskPage /> },
      { path: "history", element: <TradeHistoryPage /> },

      // Bot drill-in (pinned bot semantics)
      { path: "bots/:botId/operate", element: <BotOperatePage /> },
      { path: "bots/:botId/positions", element: <BotPositionsPage /> },
      { path: "bots/:botId/decisions", element: <BotDecisionsPage /> },
      { path: "bots/:botId/history", element: <BotHistoryPage /> },
      
      // Risk - Am I safe right now?
      { path: "risk/limits", element: <RiskLimitsPage /> },
      { path: "risk/exposure", element: <RiskExposurePage /> },
      { path: "risk/metrics", element: <RiskMetricsPage /> },
      { path: "risk/incidents", element: <RiskIncidentsPage /> },

      // Analysis - Why it's happening
      { path: "pipeline-health", element: <PipelineHealthPage /> },
      { path: "analysis/replay", element: <ReplayStudioPage /> },
      { path: "analysis/model-training", element: <ModelTrainingPage /> },
      { path: "market-context", element: <MarketContextPage /> },
      { path: "signals", element: <SignalsPage /> },
      { path: "execution", element: <ExecutionPage /> },
      
      // Trading Pipeline Integration routes
      // Feature: trading-pipeline-integration
      // **Validates: Requirements 4.5, 9.3**
      { path: "shadow-comparison", element: <ShadowComparisonPage /> },
      { path: "config-management", element: <ConfigManagementPage /> },
      { path: "replay-validation", element: <ReplayValidationPage /> },
      { path: "metrics-comparison", element: <MetricsComparisonPage /> },
      
      // Research - Offline experimentation
      { path: "backtesting", element: <BacktestingPage /> },
      { path: "data-quality", element: <DataQualityPage /> },
      
      // System - Controls & governance
      { path: "bot-management", element: <BotManagementPage /> },
      { path: "exchange-accounts", element: <ExchangeAccountsPage /> },
      { path: "profiles", element: <ProfilesPage /> },
      { path: "config", element: <SettingsHomePage /> }, // Redirect old config path to settings
      { path: "audit", element: <AuditLogPage /> },
      { path: "docs", element: <DocsPage /> },
      
      // Settings pages (Stripe-style directory)
      { path: "settings", element: <SettingsHomePage /> },
      { path: "settings/account", element: <SettingsAccountPage /> },
      { path: "settings/trading", element: <SettingsTradingPage /> },
      { path: "settings/risk", element: <SettingsRiskPage /> },
      { path: "settings/exchanges", element: <SettingsExchangesPage /> },
      { path: "settings/notifications", element: <SettingsNotificationsPage /> },
      { path: "settings/data", element: <SettingsDataPage /> },
      { path: "settings/security", element: <SettingsSecurityPage /> },
      { path: "settings/billing", element: <SettingsBillingPage /> },
      { path: "settings/system-health", element: <SettingsSystemHealthPage /> },
      { path: "settings/runtime-config", element: <RuntimeConfigPage /> },
      
      // Additional routes
      { path: "active-bot", element: <ActiveBotPage /> },
      { path: "strategies", element: <StrategiesPage /> },
      { path: "live-trading", element: <LiveTradingPage /> },
      { path: "trade-history", element: <TradeHistoryPage /> },
      { path: "profile-editor", element: <ProfileEditorPage /> },
      { path: "strategy-config", element: <StrategyConfigPage /> },
      { path: "signal-customization", element: <SignalCustomizationPage /> },
      { path: "allocator", element: <PortfolioAllocatorPage /> },
      { path: "health", element: <SystemHealthPage /> },
      { path: "tca", element: <TCAPage /> },
      { path: "risk-metrics", element: <RiskMetricsPage /> },
      { path: "promotions", element: <PromotionsPage /> },
      { path: "portfolio", element: <PortfolioPage /> },
      { path: "reporting", element: <ReportingPage /> },
      { path: "trading", element: <TradingOpsPage /> },
      { path: "trading-ops", element: <TradingOpsPage /> },
          ],
        },
      ]
    : [
        // Landing site (quantgambit.com) routes.
        { path: "/", element: <LandingPage /> },
        { path: "/auth/sign-in", element: <SignInPage /> },
        { path: "/auth/sign-up", element: <SignUpPage /> },
        // Back-compat with earlier external redirect paths.
        { path: "/sign-in", loader: () => redirect("/auth/sign-in") },
        { path: "/request-access", loader: () => redirect("/auth/sign-up") },
      ]),
]);
