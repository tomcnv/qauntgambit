/**
 * Shadow Comparison Page
 * 
 * Displays the ShadowComparisonPanel component for monitoring
 * live vs shadow pipeline decision comparison.
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 4.5**
 */

import { DashBar } from "../../components/DashBar";
import { ShadowComparisonPanel } from "../../components/ShadowComparisonPanel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { Link } from "react-router-dom";
import {
  GitCompare,
  Activity,
  Settings,
  ArrowLeft,
  Info,
  AlertTriangle,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";

export default function ShadowComparisonPage() {
  return (
    <TooltipProvider>
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        
        <main className="flex-1 p-6">
          <div className="max-w-6xl mx-auto space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <Link to="/pipeline-health">
                  <Button variant="ghost" size="sm">
                    <ArrowLeft className="h-4 w-4 mr-1" />
                    Pipeline Health
                  </Button>
                </Link>
                <Separator orientation="vertical" className="h-6" />
                <div>
                  <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                    <GitCompare className="h-6 w-6" />
                    Shadow Mode Comparison
                  </h1>
                  <p className="text-sm text-muted-foreground mt-1">
                    Compare live trading decisions against shadow pipeline configuration
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="sm" asChild>
                      <Link to="/settings/trading">
                        <Settings className="h-4 w-4 mr-1" />
                        Configure Shadow
                      </Link>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    Configure shadow mode settings and alternative configuration
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            {/* Info Banner */}
            <Card className="border-blue-500/30 bg-blue-500/5">
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-blue-600">About Shadow Mode</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Shadow mode runs an alternative pipeline configuration in parallel with live trading.
                      This allows you to validate strategy changes before deployment by comparing decisions
                      and tracking agreement rates. High divergence may indicate configuration issues or
                      opportunities for improvement.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Main Shadow Comparison Panel */}
            <ShadowComparisonPanel />

            {/* Related Links */}
            <div className="grid grid-cols-3 gap-4">
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/pipeline-health">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <Activity className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Pipeline Health</p>
                        <p className="text-xs text-muted-foreground">Monitor all pipeline layers</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/config-management">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <Settings className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Config Management</p>
                        <p className="text-xs text-muted-foreground">View configuration versions</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/metrics-comparison">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <GitCompare className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Metrics Comparison</p>
                        <p className="text-xs text-muted-foreground">Compare live vs backtest metrics</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
            </div>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
