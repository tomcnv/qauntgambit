/**
 * Kill Switch Control Panel
 * 
 * Displays kill switch status and provides trigger/reset controls.
 * Shows history of trigger/reset events.
 */

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  History,
  Power,
  PowerOff,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import {
  useKillSwitchStatus,
  useKillSwitchHistory,
  useTriggerKillSwitch,
  useResetKillSwitch,
} from "../../lib/api/quant-hooks";

const TRIGGER_REASONS = [
  { value: "manual", label: "Manual Override", description: "Operator-initiated emergency stop" },
  { value: "drawdown_breach", label: "Drawdown Breach", description: "Maximum drawdown exceeded" },
  { value: "daily_loss_breach", label: "Daily Loss Breach", description: "Daily loss limit exceeded" },
  { value: "data_integrity", label: "Data Integrity", description: "Market data integrity compromised" },
  { value: "connectivity", label: "Connectivity Issue", description: "Exchange connectivity problems" },
  { value: "other", label: "Other", description: "Other reason (specify in message)" },
];

function formatTimestamp(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function formatRelativeTime(ts: number | null): string {
  if (!ts) return "";
  const now = Date.now() / 1000;
  const diff = now - ts;
  
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

interface KillSwitchPanelProps {
  className?: string;
  compact?: boolean;
}

export function KillSwitchPanel({ className, compact = false }: KillSwitchPanelProps) {
  const [triggerReason, setTriggerReason] = useState("manual");
  const [triggerMessage, setTriggerMessage] = useState("");
  const [operatorId, setOperatorId] = useState("");
  
  const { data: statusData, isLoading, error, refetch } = useKillSwitchStatus();
  const { data: historyData } = useKillSwitchHistory(10);
  const triggerMutation = useTriggerKillSwitch();
  const resetMutation = useResetKillSwitch();

  const status = statusData?.status;
  const history = historyData?.history || [];
  const isActive = status?.is_active ?? false;
  const triggeredBy = status?.triggered_by || {};
  const triggerCount = Object.keys(triggeredBy).length;

  const handleTrigger = () => {
    triggerMutation.mutate({
      trigger: triggerReason,
      message: triggerMessage || undefined,
    });
  };

  const handleReset = () => {
    resetMutation.mutate(operatorId || undefined);
  };

  if (compact) {
    return (
      <div className={cn("flex items-center gap-3", className)}>
        {/* Compact status indicator */}
        <div className="flex items-center gap-2">
          {isActive ? (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/40">
              <ShieldAlert className="h-4 w-4 text-red-500 animate-pulse" />
              <span className="text-sm font-medium text-red-500">Kill Switch Active</span>
              <Badge variant="destructive" className="text-xs">
                {triggerCount} trigger{triggerCount !== 1 ? "s" : ""}
              </Badge>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
              <span className="text-sm font-medium text-emerald-600">Trading Active</span>
            </div>
          )}
        </div>

        {/* Quick action buttons */}
        {!isActive ? (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm" className="gap-1.5">
                <PowerOff className="h-3.5 w-3.5" />
                Emergency Stop
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2 text-red-600">
                  <AlertTriangle className="h-5 w-5" />
                  Activate Kill Switch
                </AlertDialogTitle>
                <AlertDialogDescription>
                  This will immediately stop all trading activity. The bot will not open new positions or execute decisions until the kill switch is reset.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="trigger-reason">Reason</Label>
                  <Select value={triggerReason} onValueChange={setTriggerReason}>
                    <SelectTrigger id="trigger-reason">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TRIGGER_REASONS.map((reason) => (
                        <SelectItem key={reason.value} value={reason.value}>
                          <span className="font-medium">{reason.label}</span>
                          <span className="text-xs text-muted-foreground ml-2">— {reason.description}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="trigger-message">Message (optional)</Label>
                  <Textarea
                    id="trigger-message"
                    placeholder="Additional details..."
                    value={triggerMessage}
                    onChange={(e) => setTriggerMessage(e.target.value)}
                    rows={2}
                  />
                </div>
              </div>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleTrigger}
                  className="bg-red-600 hover:bg-red-700"
                  disabled={triggerMutation.isPending}
                >
                  {triggerMutation.isPending ? "Activating..." : "Activate Kill Switch"}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5 border-emerald-500/50 text-emerald-600 hover:bg-emerald-500/10">
                <Power className="h-3.5 w-3.5" />
                Reset & Resume
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2 text-emerald-600">
                  <CheckCircle className="h-5 w-5" />
                  Reset Kill Switch
                </AlertDialogTitle>
                <AlertDialogDescription>
                  This will reset the kill switch and resume trading. Make sure you have addressed the issues that triggered the kill switch.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="operator-id">Your name (for audit)</Label>
                  <Input
                    id="operator-id"
                    placeholder="e.g., John"
                    value={operatorId}
                    onChange={(e) => setOperatorId(e.target.value)}
                  />
                </div>
                {triggerCount > 0 && (
                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
                    <p className="text-sm text-amber-600 dark:text-amber-400">
                      <strong>Active triggers:</strong> {Object.keys(triggeredBy).join(", ")}
                    </p>
                    {status?.message && (
                      <p className="text-xs text-amber-600/80 dark:text-amber-400/80 mt-1">
                        {status.message}
                      </p>
                    )}
                  </div>
                )}
              </div>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleReset}
                  className="bg-emerald-600 hover:bg-emerald-700"
                  disabled={resetMutation.isPending}
                >
                  {resetMutation.isPending ? "Resetting..." : "Reset Kill Switch"}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    );
  }

  // Full panel view
  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Kill Switch Control</CardTitle>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => refetch()}>
                <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Refresh status</TooltipContent>
          </Tooltip>
        </div>
        <CardDescription>
          Emergency trading halt control with audit trail
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-4">
        {/* Status Display */}
        <div className={cn(
          "p-4 rounded-lg border",
          isActive 
            ? "bg-red-500/10 border-red-500/40" 
            : "bg-emerald-500/10 border-emerald-500/30"
        )}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isActive ? (
                <ShieldAlert className="h-8 w-8 text-red-500 animate-pulse" />
              ) : (
                <ShieldCheck className="h-8 w-8 text-emerald-500" />
              )}
              <div>
                <p className={cn(
                  "font-semibold text-lg",
                  isActive ? "text-red-600" : "text-emerald-600"
                )}>
                  {isActive ? "Kill Switch ACTIVE" : "Trading Active"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {isActive 
                    ? `${triggerCount} trigger${triggerCount !== 1 ? "s" : ""} active`
                    : status?.blocks_count 
                      ? `${status.blocks_count} decisions blocked while active`
                      : "System operating normally"
                  }
                </p>
              </div>
            </div>
            {isActive && status?.last_reset_ts && (
              <div className="text-right text-sm text-muted-foreground">
                <p>Last reset: {formatRelativeTime(status.last_reset_ts)}</p>
                <p className="text-xs">by {status.last_reset_by || "system"}</p>
              </div>
            )}
          </div>

          {/* Active triggers */}
          {isActive && triggerCount > 0 && (
            <div className="mt-3 pt-3 border-t border-red-500/20">
              <p className="text-xs font-medium text-red-600 mb-2">Active Triggers:</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(triggeredBy).map(([trigger, ts]) => (
                  <Tooltip key={trigger}>
                    <TooltipTrigger asChild>
                      <Badge variant="destructive" className="text-xs">
                        {trigger}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      Triggered at {formatTimestamp(ts)}
                    </TooltipContent>
                  </Tooltip>
                ))}
              </div>
              {status?.message && (
                <p className="mt-2 text-sm text-red-600/80">{status.message}</p>
              )}
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          {!isActive ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" className="flex-1 gap-2">
                  <PowerOff className="h-4 w-4" />
                  Activate Kill Switch
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="flex items-center gap-2 text-red-600">
                    <AlertTriangle className="h-5 w-5" />
                    Activate Kill Switch
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    This will immediately stop all trading activity. The bot will not open new positions or execute decisions until the kill switch is reset.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="trigger-reason-full">Reason</Label>
                    <Select value={triggerReason} onValueChange={setTriggerReason}>
                      <SelectTrigger id="trigger-reason-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TRIGGER_REASONS.map((reason) => (
                          <SelectItem key={reason.value} value={reason.value}>
                            <div>
                              <span className="font-medium">{reason.label}</span>
                              <p className="text-xs text-muted-foreground">{reason.description}</p>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="trigger-message-full">Message (optional)</Label>
                    <Textarea
                      id="trigger-message-full"
                      placeholder="Additional details about why you're activating the kill switch..."
                      value={triggerMessage}
                      onChange={(e) => setTriggerMessage(e.target.value)}
                      rows={3}
                    />
                  </div>
                </div>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={handleTrigger}
                    className="bg-red-600 hover:bg-red-700"
                    disabled={triggerMutation.isPending}
                  >
                    {triggerMutation.isPending ? "Activating..." : "Activate Kill Switch"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" className="flex-1 gap-2 border-emerald-500/50 text-emerald-600 hover:bg-emerald-500/10">
                  <Power className="h-4 w-4" />
                  Reset Kill Switch
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="flex items-center gap-2 text-emerald-600">
                    <CheckCircle className="h-5 w-5" />
                    Reset Kill Switch
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    This will reset the kill switch and resume trading. Ensure you have addressed all issues that triggered the kill switch.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="operator-id-full">Your name (for audit)</Label>
                    <Input
                      id="operator-id-full"
                      placeholder="e.g., John Smith"
                      value={operatorId}
                      onChange={(e) => setOperatorId(e.target.value)}
                    />
                  </div>
                  
                  {triggerCount > 0 && (
                    <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
                      <p className="text-sm font-medium text-amber-600 dark:text-amber-400 mb-1">
                        Triggers to be cleared:
                      </p>
                      <ul className="text-sm text-amber-600/80 dark:text-amber-400/80 space-y-1">
                        {Object.entries(triggeredBy).map(([trigger, ts]) => (
                          <li key={trigger}>
                            • {trigger} (triggered {formatRelativeTime(ts)})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={handleReset}
                    className="bg-emerald-600 hover:bg-emerald-700"
                    disabled={resetMutation.isPending}
                  >
                    {resetMutation.isPending ? "Resetting..." : "Reset & Resume Trading"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>

        {/* History */}
        {history.length > 0 && (
          <div className="pt-2">
            <div className="flex items-center gap-2 mb-2">
              <History className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium text-muted-foreground">Recent Activity</span>
            </div>
            <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
              {history.map((event, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-2 text-xs p-2 rounded-md bg-muted/30"
                >
                  {event.type === "trigger" ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                  ) : (
                    <CheckCircle className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  )}
                  <span className="flex-1">
                    {event.type === "trigger" ? (
                      <>
                        <span className="font-medium text-red-600">Triggered</span>
                        {" by "}
                        <span className="font-medium">{event.trigger}</span>
                        {event.message && (
                          <span className="text-muted-foreground"> — {event.message}</span>
                        )}
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-emerald-600">Reset</span>
                        {" by "}
                        <span className="font-medium">{event.operator_id || "system"}</span>
                      </>
                    )}
                  </span>
                  <span className="text-muted-foreground shrink-0">
                    <Clock className="h-3 w-3 inline mr-1" />
                    {formatRelativeTime(event.timestamp)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <p className="text-sm text-red-600">
              Failed to load kill switch status. The API may be unavailable.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default KillSwitchPanel;
