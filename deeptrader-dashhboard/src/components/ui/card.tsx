import { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type DivProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, ...props }: DivProps) {
  return (
    <div
      className={cn(
        // Base styles
        "rounded-2xl p-6 backdrop-blur-xl backdrop-saturate-150 transition-all duration-200",
        // Light mode
        "border border-border/50 bg-card shadow-sm",
        // Dark mode - frosted glass effect
        "dark:border-white/[0.06] dark:bg-[hsl(228_40%_12%/0.75)]",
        "dark:shadow-[0_0_0_1px_rgba(255,255,255,0.03),0_8px_32px_-8px_rgba(0,0,0,0.5),0_4px_16px_-4px_rgba(100,140,200,0.08)]",
        // Subtle inner glow for frosted depth
        "dark:ring-1 dark:ring-inset dark:ring-white/[0.03]",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: DivProps) {
  return (
    <div
      className={cn("mb-4 flex flex-col gap-1 text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

type HeadingProps = HTMLAttributes<HTMLHeadingElement>;

export function CardTitle({ className, ...props }: HeadingProps) {
  return (
    <h3 className={cn("text-lg font-semibold text-foreground", className)} {...props} />
  );
}

export function CardDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: DivProps) {
  return <div className={cn("text-sm text-foreground", className)} {...props} />;
}

