import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  helper?: string;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  variant?: "default" | "success" | "warning" | "outline";
  icon?: React.ReactNode;
  className?: string;
}

export function MetricCard({
  label,
  value,
  helper,
  trend,
  trendValue,
  variant = "default",
  icon,
  className,
}: MetricCardProps) {
  const variantStyles = {
    default: "border-white/5 bg-white/5",
    success: "border-emerald-400/20 bg-emerald-500/10",
    warning: "border-amber-400/20 bg-amber-500/10",
    outline: "border-white/10 bg-transparent",
  };

  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-emerald-400" : trend === "down" ? "text-red-400" : "text-muted-foreground";

  return (
    <Card className={cn("border-white/5", variantStyles[variant], className)}>
      <CardHeader className="space-y-1 pb-2">
        <CardTitle className="text-xs uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
          {icon && <span className="text-muted-foreground">{icon}</span>}
          {label}
        </CardTitle>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold text-white">{value}</span>
          {trend && trendValue && (
            <div className={cn("flex items-center gap-1 text-xs font-medium", trendColor)}>
              <TrendIcon className="h-3 w-3" />
              <span>{trendValue}</span>
            </div>
          )}
        </div>
      </CardHeader>
      {helper && (
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">{helper}</p>
        </CardContent>
      )}
    </Card>
  );
}





