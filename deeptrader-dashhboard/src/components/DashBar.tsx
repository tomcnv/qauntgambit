/**
 * DashBar - Self-contained dashboard status bar
 * 
 * A wrapper around TruthBar that fetches its own data, making it easy to add
 * to any page without manual data wiring.
 * 
 * Shows:
 * - Trading mode (Paper/Live) + Exchange
 * - Bot name + running state
 * - Gates status
 * - Safety metrics (daily loss, exposure)
 */

import { TruthBar } from "./market-context/TruthBar";
import { useMarketFitData } from "../lib/api/market-fit-hooks";
import { TooltipProvider } from "./ui/tooltip";

export function DashBar() {
  const marketFitData = useMarketFitData();

  return (
    <TooltipProvider>
      <TruthBar
        botName={marketFitData.botName}
        botRunning={marketFitData.botRunning}
        botRunningSince={marketFitData.botRunningSince}
        profileName={marketFitData.profileName}
        profileVersion={marketFitData.profileVersion}
        gates={marketFitData.gates}
        safety={marketFitData.safety}
        venueHealth={marketFitData.venueHealth}
      />
    </TooltipProvider>
  );
}

export default DashBar;

