/**
 * Bot Startup Modal
 * Shows progress during bot startup with ability to cancel
 */

import { useEffect, useState, useCallback } from "react";
import { Dialog, DialogContent } from "./ui/dialog";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { cn } from "../lib/utils";
import { CheckCircle2, Circle, Loader2, X, AlertCircle, Zap } from "lucide-react";

// Startup phases
type StartupPhase = 
  | "sending_command"
  | "initializing"
  | "connecting"
  | "warmup"
  | "ready"
  | "error"
  | "cancelled";

interface PhaseConfig {
  label: string;
  description: string;
  weight: number; // Percentage of total progress
}

const PHASES: Record<StartupPhase, PhaseConfig> = {
  sending_command: {
    label: "Sending Command",
    description: "Dispatching start command to trading engine...",
    weight: 10,
  },
  initializing: {
    label: "Initializing Bot",
    description: "Loading configuration and profiles...",
    weight: 20,
  },
  connecting: {
    label: "Connecting to Exchange",
    description: "Establishing WebSocket connections...",
    weight: 25,
  },
  warmup: {
    label: "Warming Up Data",
    description: "Loading market data and computing indicators...",
    weight: 35,
  },
  ready: {
    label: "Ready",
    description: "Bot is now actively trading",
    weight: 10,
  },
  error: {
    label: "Error",
    description: "Startup failed",
    weight: 0,
  },
  cancelled: {
    label: "Cancelled",
    description: "Startup was cancelled",
    weight: 0,
  },
};

const PHASE_ORDER: StartupPhase[] = [
  "sending_command",
  "initializing",
  "connecting",
  "warmup",
  "ready",
];

interface BotStartupModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCancel: () => void;
  currentPhase: StartupPhase;
  warmupProgress?: number; // 0-100
  warmupDetail?: {
    sampleCount?: number;
    minSamples?: number;
    candleCount?: number;
    minCandles?: number;
  };
  errorMessage?: string;
  botName?: string;
  tradingMode?: string;
  qualityMessage?: string;
  onDismiss?: () => void;
}

export function BotStartupModal({
  isOpen,
  onClose,
  onCancel,
  currentPhase,
  warmupProgress = 0,
  warmupDetail,
  errorMessage,
  botName,
  tradingMode,
  qualityMessage,
  onDismiss,
}: BotStartupModalProps) {
  const [animatedProgress, setAnimatedProgress] = useState(0);

  // Calculate total progress based on phase
  const calculateProgress = useCallback(() => {
    if (currentPhase === "error" || currentPhase === "cancelled") return animatedProgress;
    if (currentPhase === "ready") return 100;

    const phaseIndex = PHASE_ORDER.indexOf(currentPhase);
    if (phaseIndex === -1) return 0;

    // Sum up completed phases
    let completed = 0;
    for (let i = 0; i < phaseIndex; i++) {
      completed += PHASES[PHASE_ORDER[i]].weight;
    }

    // Add current phase progress
    const currentWeight = PHASES[currentPhase].weight;
    if (currentPhase === "warmup") {
      // Use actual warmup progress
      completed += (warmupProgress / 100) * currentWeight;
    } else {
      // Simulate progress within phase
      completed += currentWeight * 0.5;
    }

    return Math.min(completed, 99);
  }, [currentPhase, warmupProgress, animatedProgress]);

  // Animate progress bar
  useEffect(() => {
    const target = calculateProgress();
    const diff = target - animatedProgress;
    if (Math.abs(diff) > 0.5) {
      const timer = setTimeout(() => {
        setAnimatedProgress((prev) => prev + diff * 0.2);
      }, 50);
      return () => clearTimeout(timer);
    } else {
      setAnimatedProgress(target);
    }
  }, [calculateProgress, animatedProgress]);

  // Auto-close on ready after a short delay
  useEffect(() => {
    if (currentPhase === "ready") {
      const timer = setTimeout(() => {
        onClose();
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [currentPhase, onClose]);

  const getPhaseStatus = (phase: StartupPhase) => {
    if (currentPhase === "error" || currentPhase === "cancelled") {
      const idx = PHASE_ORDER.indexOf(phase);
      const currentIdx = PHASE_ORDER.indexOf(currentPhase);
      if (currentIdx === -1) return "pending";
      return idx < currentIdx ? "complete" : "pending";
    }

    const currentIndex = PHASE_ORDER.indexOf(currentPhase);
    const phaseIndex = PHASE_ORDER.indexOf(phase);

    if (phaseIndex < currentIndex) return "complete";
    if (phaseIndex === currentIndex) return "active";
    return "pending";
  };

  const isTerminal = currentPhase === "ready" || currentPhase === "error" || currentPhase === "cancelled";

  const warmupLabel = (() => {
    if (!warmupDetail) return `${Math.round(warmupProgress)}%`;
    const samples = warmupDetail.sampleCount ?? 0;
    const minSamples = warmupDetail.minSamples ?? 0;
    const candles = warmupDetail.candleCount ?? 0;
    const minCandles = warmupDetail.minCandles ?? 0;
    const samplesPart = minSamples ? `${samples}/${minSamples} samples` : `${samples} samples`;
    const candlesPart = minCandles ? `${candles}/${minCandles} candles` : `${candles} candles`;
    return `${samplesPart} • ${candlesPart}`;
  })();

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onDismiss ? onDismiss() : onClose()}>
      <DialogContent className="sm:max-w-md">
        <div className="space-y-6">
          {/* Header */}
          <div className="space-y-2 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              {currentPhase === "ready" ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              ) : currentPhase === "error" ? (
                <AlertCircle className="h-6 w-6 text-red-500" />
              ) : currentPhase === "cancelled" ? (
                <X className="h-6 w-6 text-muted-foreground" />
              ) : (
                <Zap className="h-6 w-6 text-primary animate-pulse" />
              )}
            </div>
            <h2 className="text-lg font-semibold">
              {currentPhase === "ready"
                ? "Bot Started!"
                : currentPhase === "error"
                ? "Startup Failed"
                : currentPhase === "cancelled"
                ? "Startup Cancelled"
                : "Starting Bot"}
            </h2>
            {botName && (
              <p className="text-sm text-muted-foreground">
                {botName}
                {tradingMode && (
                  <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs">
                    {tradingMode === "paper" ? "📝 Paper Mode" : tradingMode === "demo" ? "🧪 Demo Trading" : "🔥 Live Trading"}
                  </span>
                )}
              </p>
            )}
          </div>

          {/* Progress Bar */}
          <div className="space-y-2">
            <Progress value={animatedProgress} className="h-2" />
            <p className="text-center text-sm text-muted-foreground">
              {currentPhase === "ready"
                ? "Ready to trade"
                : currentPhase === "error"
                ? errorMessage || "Startup failed"
                : currentPhase === "cancelled"
                ? "Startup was cancelled"
                : PHASES[currentPhase].description}
            </p>
            {qualityMessage && currentPhase !== "error" && (
              <div className="text-center text-sm text-amber-600">
                {qualityMessage}
              </div>
            )}
            {currentPhase === "error" && (
              <div className="text-center text-sm text-red-500">
                {errorMessage || "Request failed. Please retry."}
              </div>
            )}
          </div>

          {/* Phase Steps */}
          <div className="space-y-3">
            {PHASE_ORDER.slice(0, -1).map((phase) => {
              const status = getPhaseStatus(phase);
              const config = PHASES[phase];

              return (
                <div
                  key={phase}
                  className={cn(
                    "flex items-center gap-3 text-sm transition-opacity",
                    status === "pending" && "opacity-40"
                  )}
                >
                  {status === "complete" ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                  ) : status === "active" ? (
                    <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                  )}
                  <span
                    className={cn(
                      status === "active" && "text-foreground font-medium",
                      status === "complete" && "text-muted-foreground"
                    )}
                  >
                    {config.label}
                  </span>
                  {status === "active" && phase === "warmup" && warmupProgress >= 0 && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {warmupLabel}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            {!isTerminal && (
              <>
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={onCancel}
                >
                  <X className="mr-2 h-4 w-4" />
                  Cancel
                </Button>
                <Button
                  variant="ghost"
                  className="flex-1"
                  onClick={onDismiss || onClose}
                >
                  Hide
                </Button>
              </>
            )}
            {currentPhase === "ready" && (
              <Button className="flex-1" onClick={onClose}>
                <CheckCircle2 className="mr-2 h-4 w-4" />
                Done
              </Button>
            )}
            {(currentPhase === "error" || currentPhase === "cancelled") && (
              <Button variant="outline" className="flex-1" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Hook to manage startup state
export function useBotStartupModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [phase, setPhase] = useState<StartupPhase>("sending_command");
  const [errorMessage, setErrorMessage] = useState<string>();
  const [botName, setBotName] = useState<string>();
  const [tradingMode, setTradingMode] = useState<string>();

  const startStartup = useCallback((name?: string, mode?: string) => {
    setPhase("sending_command");
    setErrorMessage(undefined);
    setBotName(name);
    setTradingMode(mode);
    setIsOpen(true);
  }, []);

  const updatePhase = useCallback((newPhase: StartupPhase) => {
    setPhase(newPhase);
  }, []);

  const setError = useCallback((message: string) => {
    setErrorMessage(message);
    setPhase("error");
  }, []);

  const cancel = useCallback(() => {
    setPhase("cancelled");
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    // Reset state after close animation
    setTimeout(() => {
      setPhase("sending_command");
      setErrorMessage(undefined);
    }, 300);
  }, []);

  return {
    isOpen,
    phase,
    errorMessage,
    botName,
    tradingMode,
    startStartup,
    updatePhase,
    setError,
    cancel,
    close,
  };
}
