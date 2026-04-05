import { useState } from "react";
import {
  AlertTriangle,
  Ban,
  ChevronDown,
  Layers,
  Pause,
  Play,
  Power,
  Shield,
  Square,
  User,
  Wifi,
  XCircle,
} from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";

interface BotControlsProps {
  botState: "running" | "paused" | "stopped" | "degraded";
  pausedBy?: "user" | "guardrail" | "connectivity";
  pauseReason?: string;
  pendingOrdersCount: number;
  positionsCount: number;
  onRun: () => void;
  onPause: () => void;
  onHalt: (options: { cancelOrders: boolean; closePositions: boolean }) => void;
  onCancelAllOrders: () => void;
  onFlattenAll: () => void;
  isLoading?: boolean;
  className?: string;
}

export function BotControls({
  botState,
  pausedBy,
  pauseReason,
  pendingOrdersCount,
  positionsCount,
  onRun,
  onPause,
  onHalt,
  onCancelAllOrders,
  onFlattenAll,
  isLoading,
  className,
}: BotControlsProps) {
  const [haltOptions, setHaltOptions] = useState({
    cancelOrders: true,
    closePositions: false,
  });

  const stateConfig = {
    running: {
      color: "bg-emerald-500",
      text: "Running",
      icon: Play,
    },
    paused: {
      color: "bg-amber-500",
      text: "Paused",
      icon: Pause,
    },
    stopped: {
      color: "bg-red-500",
      text: "Stopped",
      icon: Square,
    },
    degraded: {
      color: "bg-orange-500",
      text: "Degraded",
      icon: AlertTriangle,
    },
  };

  const pausedByConfig = {
    user: { icon: User, text: "by User", color: "text-blue-500" },
    guardrail: { icon: Shield, text: "by Guardrail", color: "text-amber-500" },
    connectivity: { icon: Wifi, text: "by Connectivity", color: "text-red-500" },
  };

  const config = stateConfig[botState];
  const StateIcon = config.icon;
  const PausedByIcon = pausedBy ? pausedByConfig[pausedBy].icon : null;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {/* State indicator */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 border">
        <div className={cn("h-2 w-2 rounded-full animate-pulse", config.color)} />
        <span className="text-sm font-medium">{config.text}</span>
        {pausedBy && (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className={cn("flex items-center gap-1 text-xs", pausedByConfig[pausedBy].color)}>
                {PausedByIcon && <PausedByIcon className="h-3 w-3" />}
                <span>{pausedByConfig[pausedBy].text}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {pauseReason || `Paused ${pausedByConfig[pausedBy].text}`}
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {/* Main controls */}
      <div className="flex items-center gap-1">
        {/* Run button */}
        {botState !== "running" && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5"
                onClick={onRun}
                disabled={isLoading}
              >
                <Play className="h-3.5 w-3.5 text-emerald-500" />
                Run
              </Button>
            </TooltipTrigger>
            <TooltipContent>Resume trading</TooltipContent>
          </Tooltip>
        )}

        {/* Pause button */}
        {botState === "running" && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5"
                onClick={onPause}
                disabled={isLoading}
              >
                <Pause className="h-3.5 w-3.5 text-amber-500" />
                Pause
              </Button>
            </TooltipTrigger>
            <TooltipContent>Pause trading (keeps positions)</TooltipContent>
          </Tooltip>
        )}

        {/* Halt button with confirmation */}
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 border-red-500/30 hover:bg-red-500/10"
              disabled={isLoading}
            >
              <Square className="h-3.5 w-3.5 text-red-500" />
              Halt
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-500" />
                Emergency Halt
              </AlertDialogTitle>
              <AlertDialogDescription className="space-y-3">
                <p>This will immediately stop the bot. Choose what to do with open orders and positions:</p>
                
                <div className="space-y-2 p-3 rounded-lg bg-muted/50">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={haltOptions.cancelOrders}
                      onChange={(e) => setHaltOptions(o => ({ ...o, cancelOrders: e.target.checked }))}
                      className="h-4 w-4 rounded border-border"
                    />
                    <div>
                      <p className="text-sm font-medium text-foreground">Cancel all open orders</p>
                      <p className="text-xs text-muted-foreground">
                        {pendingOrdersCount} pending order{pendingOrdersCount !== 1 ? "s" : ""} will be canceled
                      </p>
                    </div>
                  </label>
                  
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={haltOptions.closePositions}
                      onChange={(e) => setHaltOptions(o => ({ ...o, closePositions: e.target.checked }))}
                      className="h-4 w-4 rounded border-border"
                    />
                    <div>
                      <p className="text-sm font-medium text-foreground">Close all positions (flatten)</p>
                      <p className="text-xs text-muted-foreground">
                        {positionsCount} position{positionsCount !== 1 ? "s" : ""} will be market closed
                      </p>
                    </div>
                  </label>
                </div>

                {haltOptions.closePositions && (
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
                    <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                    <p className="text-xs text-amber-600 dark:text-amber-400">
                      Flattening positions will execute market orders immediately. This may result in slippage.
                    </p>
                  </div>
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => onHalt(haltOptions)}
                className="bg-red-500 hover:bg-red-600"
              >
                Halt Bot
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      {/* Quick actions dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-8 px-2">
            <span className="sr-only">More actions</span>
            <ChevronDown className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuItem
            onClick={onCancelAllOrders}
            disabled={pendingOrdersCount === 0 || isLoading}
            className="gap-2"
          >
            <XCircle className="h-4 w-4 text-amber-500" />
            <div className="flex-1">
              <p>Cancel All Orders</p>
              <p className="text-[10px] text-muted-foreground">{pendingOrdersCount} pending</p>
            </div>
          </DropdownMenuItem>
          
          <DropdownMenuSeparator />
          
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <DropdownMenuItem
                onSelect={(e) => e.preventDefault()}
                disabled={positionsCount === 0 || isLoading}
                className="gap-2"
              >
                <Layers className="h-4 w-4 text-red-500" />
                <div className="flex-1">
                  <p>Flatten All Positions</p>
                  <p className="text-[10px] text-muted-foreground">{positionsCount} open</p>
                </div>
              </DropdownMenuItem>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <Layers className="h-5 w-5 text-red-500" />
                  Flatten All Positions
                </AlertDialogTitle>
                <AlertDialogDescription className="space-y-3">
                  <p>
                    This will close all {positionsCount} position{positionsCount !== 1 ? "s" : ""} with market orders.
                  </p>
                  
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
                    <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                    <p className="text-xs text-amber-600 dark:text-amber-400">
                      Market orders may experience slippage. Consider using limit orders for large positions.
                    </p>
                  </div>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={onFlattenAll}
                  className="bg-red-500 hover:bg-red-600"
                >
                  Flatten All
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}



