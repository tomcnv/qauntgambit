/**
 * TradeCopilotIcon — Small icon button that opens the copilot
 * with a specific trade's context pre-loaded.
 *
 * Renders on trade rows and in the TradeInspectorDrawer.
 */

import { Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCopilotStore, type QuantTrade } from "@/store/copilot-store";

export interface TradeCopilotIconProps {
  trade: QuantTrade;
}

export function TradeCopilotIcon({ trade }: TradeCopilotIconProps) {
  const handleClick = () => {
    useCopilotStore.getState().openWithTradeContext(trade);
  };

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClick}
            data-testid="trade-copilot-icon"
            aria-label="Ask Copilot about this trade"
          >
            <Bot className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Ask Copilot about this trade</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
