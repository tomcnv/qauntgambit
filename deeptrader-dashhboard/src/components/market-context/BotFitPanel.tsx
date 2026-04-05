/**
 * BotFitPanel - Profile fit score with breakdown
 * 
 * Shows:
 * - Overall fit score (0-100)
 * - Breakdown by component:
 *   - Microstructure fit
 *   - Regime fit
 *   - Execution fit
 *   - Risk fit
 * - Recommended actions
 * - Expected concentration if started
 */

import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Info,
  Lightbulb,
  Scale,
  Shield,
  Target,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Progress } from "../ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { BotFitScore } from "./types";

// ============================================================================
// TYPES
// ============================================================================

interface BotFitPanelProps {
  fitScore: BotFitScore;
  botRunning: boolean;
  profileName: string | null;
  className?: string;
}

// ============================================================================
// SCORE RING
// ============================================================================

function ScoreRing({ score, size = 80 }: { score: number; size?: number }) {
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (score / 100) * circumference;
  
  const getColor = (s: number) => {
    if (s >= 70) return "stroke-emerald-500";
    if (s >= 50) return "stroke-amber-500";
    return "stroke-red-500";
  };
  
  const getTextColor = (s: number) => {
    if (s >= 70) return "text-emerald-500";
    if (s >= 50) return "text-amber-500";
    return "text-red-500";
  };
  
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/30"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={cn("transition-all duration-500", getColor(score))}
        />
      </svg>
      {/* Score text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-2xl font-bold", getTextColor(score))}>{score}</span>
      </div>
    </div>
  );
}

// ============================================================================
// FIT COMPONENT BAR
// ============================================================================

function FitComponentBar({ 
  label, 
  score, 
  icon: Icon,
  description,
}: { 
  label: string;
  score: number;
  icon: React.ElementType;
  description: string;
}) {
  const getColor = (s: number) => {
    if (s >= 70) return "bg-emerald-500";
    if (s >= 50) return "bg-amber-500";
    return "bg-red-500";
  };
  
  const getTextColor = (s: number) => {
    if (s >= 70) return "text-emerald-500";
    if (s >= 50) return "text-amber-500";
    return "text-red-500";
  };
  
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="space-y-1 cursor-default">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <Icon className="h-3 w-3 text-muted-foreground" />
              <span className="text-muted-foreground">{label}</span>
            </div>
            <span className={cn("font-mono font-medium", getTextColor(score))}>
              {score}
            </span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div 
              className={cn("h-full rounded-full transition-all", getColor(score))}
              style={{ width: `${score}%` }}
            />
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="left" className="text-xs max-w-[200px]">
        {description}
      </TooltipContent>
    </Tooltip>
  );
}

// ============================================================================
// RECOMMENDATION ITEM
// ============================================================================

function RecommendationItem({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <Lightbulb className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
      <span className="text-muted-foreground">{text}</span>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function BotFitPanel({ 
  fitScore, 
  botRunning, 
  profileName,
  className,
}: BotFitPanelProps) {
  const getOverallStatus = () => {
    if (fitScore.overall >= 70) return { label: "Good Fit", color: "text-emerald-500" };
    if (fitScore.overall >= 50) return { label: "Moderate Fit", color: "text-amber-500" };
    return { label: "Poor Fit", color: "text-red-500" };
  };
  
  const status = getOverallStatus();
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Profile Fit</CardTitle>
            {profileName && (
              <Badge variant="outline" className="text-[10px]">
                {profileName}
              </Badge>
            )}
          </div>
          <Badge 
            variant="outline" 
            className={cn("text-[10px]", status.color)}
          >
            {status.label}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-4">
        {/* Score Ring + Components */}
        <div className="flex gap-4">
          {/* Score Ring */}
          <div className="flex flex-col items-center">
            <ScoreRing score={fitScore.overall} />
            <span className="text-[10px] text-muted-foreground mt-1">Overall</span>
          </div>
          
          {/* Component Breakdown */}
          <div className="flex-1 space-y-2">
            <FitComponentBar 
              label="Microstructure" 
              score={fitScore.microstructureFit}
              icon={Scale}
              description="How well current spreads and liquidity match the profile's requirements"
            />
            <FitComponentBar 
              label="Regime" 
              score={fitScore.regimeFit}
              icon={Activity}
              description="How well current volatility and market regime align with the profile's optimal conditions"
            />
            <FitComponentBar 
              label="Execution" 
              score={fitScore.executionFit}
              icon={Zap}
              description="How well current latency and venue conditions support the profile's execution needs"
            />
            <FitComponentBar 
              label="Risk" 
              score={fitScore.riskFit}
              icon={Shield}
              description="How well current risk conditions and anomaly levels fit within the profile's risk tolerance"
            />
          </div>
        </div>
        
        {/* Expected Concentration */}
        {fitScore.expectedConcentration !== undefined && (
          <div className="flex items-center justify-between p-2 rounded-lg bg-muted/30 text-xs">
            <div className="flex items-center gap-1.5">
              <Target className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">
                {botRunning ? "Current" : "Expected"} Concentration
              </span>
            </div>
            <span className={cn(
              "font-mono font-medium",
              fitScore.expectedConcentration > 50 ? "text-amber-500" : "text-emerald-500"
            )}>
              {fitScore.expectedConcentration.toFixed(0)}%
            </span>
          </div>
        )}
        
        {/* Recommendations */}
        {fitScore.recommendations.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Recommendations
            </h4>
            <div className="space-y-2">
              {fitScore.recommendations.map((rec, idx) => (
                <RecommendationItem key={idx} text={rec} />
              ))}
            </div>
          </div>
        )}
        
        {/* All Good State */}
        {fitScore.recommendations.length === 0 && fitScore.overall >= 70 && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 text-xs text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-4 w-4" />
            <span>Conditions are favorable for the current profile</span>
          </div>
        )}
        
        {/* Warning State */}
        {fitScore.overall < 50 && (
          <div className="flex items-start gap-2 p-2 rounded-lg bg-red-500/10 text-xs text-red-600 dark:text-red-400">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div>
              <span className="font-medium">Poor market fit detected</span>
              <p className="text-red-500/80 mt-0.5">
                Consider pausing or switching to a more suitable profile for current conditions.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

