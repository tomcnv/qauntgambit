import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { cn } from "../../lib/utils";
import { ReactNode } from "react";

interface ChartContainerProps {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
  height?: string;
}

export function ChartContainer({
  title,
  description,
  children,
  className,
  actions,
  height = "h-64",
}: ChartContainerProps) {
  return (
    <Card className={cn("border-white/5 bg-black/40", className)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">{title}</CardTitle>
          {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </CardHeader>
      <CardContent className={cn(height, "w-full")}>{children}</CardContent>
    </Card>
  );
}





