import { useTheme } from "./theme-provider";
import { cn } from "../lib/utils";

type LogoSize = "sm" | "md" | "lg";

type LogoProps = {
  className?: string;
  size?: LogoSize;
  showText?: boolean;
  iconOnly?: boolean;
};

export default function Logo({ className, size = "md", showText = true, iconOnly = false }: LogoProps) {
  const { theme } = useTheme();
  
  const sizeClasses: Record<LogoSize, { img: string; text: string }> = {
    sm: { img: "h-6 w-auto", text: "text-sm" },
    md: { img: "h-8 w-auto", text: "text-base" },
    lg: { img: "h-10 w-auto", text: "text-lg" },
  };

  // Use dark logo on dark theme, light logo on light theme
  const logoSrc = theme === "dark" ? "/quantgambit-dark.png" : "/quantgambit-light.png";

  if (iconOnly) {
    return (
      <div className={cn("flex items-center justify-center rounded-lg bg-primary/10", className)}>
        <img src={logoSrc} alt="QuantGambit" className={sizeClasses[size].img} />
      </div>
    );
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <img src={logoSrc} alt="QuantGambit" className={sizeClasses[size].img} />
    </div>
  );
}
