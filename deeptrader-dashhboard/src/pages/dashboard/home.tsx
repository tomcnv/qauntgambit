import { useActiveConfig } from "../../lib/api/hooks";
import FleetOverviewPage from "./fleet-overview";
import Overview from "./overview";

/**
 * /dashboard behavior:
 * - If no bot is pinned (no active bot exchange config), show Fleet overview.
 * - If a bot is pinned, show bot-scoped mission control overview.
 */
export default function DashboardHomePage() {
  const { data: activeConfigData, isLoading } = useActiveConfig();

  if (isLoading) {
    return <FleetOverviewPage />;
  }

  const pinned = Boolean((activeConfigData as any)?.active?.id);
  return pinned ? <Overview /> : <FleetOverviewPage />;
}








