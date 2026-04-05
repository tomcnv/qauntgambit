/**
 * AdvancedSection - Collapsible section for advanced analytics
 */

import { useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../ui/collapsible";
import { Button } from "../ui/button";
import { ChevronDown, Settings2 } from "lucide-react";
import { ThresholdSweepChart } from "./ThresholdSweepChart";
import { ErrorDistributionChart } from "./ErrorDistributionChart";
import type { ThresholdSweepPoint, ErrorDistribution } from "../../types/orderbookModel";

interface AdvancedSectionProps {
  sweepData: ThresholdSweepPoint[] | undefined;
  errorDistData: ErrorDistribution | undefined;
  isLoading?: boolean;
}

export function AdvancedSection({
  sweepData,
  errorDistData,
  isLoading,
}: AdvancedSectionProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="outline"
          className="w-full justify-between h-9"
        >
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            <span>Advanced Analytics</span>
          </div>
          <ChevronDown
            className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <ThresholdSweepChart data={sweepData} isLoading={isLoading} />
          <ErrorDistributionChart data={errorDistData} isLoading={isLoading} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

