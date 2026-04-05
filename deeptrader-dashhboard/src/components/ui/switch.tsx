import { forwardRef, InputHTMLAttributes, useCallback } from "react";
import { cn } from "../../lib/utils";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
  // Radix-style API compatibility
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = forwardRef<HTMLInputElement, SwitchProps>(({ className, label, onCheckedChange, onChange, ...props }, ref) => {
  // Combine onChange and onCheckedChange
  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    onChange?.(e);
    onCheckedChange?.(e.target.checked);
  }, [onChange, onCheckedChange]);

  return (
    <label className={cn("flex items-center gap-3 cursor-pointer", className)}>
      <div className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-primary/60 focus-within:ring-offset-2 focus-within:ring-offset-background">
        <input
          type="checkbox"
          className="peer sr-only"
          ref={ref}
          onChange={handleChange}
          {...props}
        />
        <div className="h-6 w-11 rounded-full border-2 border-border bg-muted transition-colors peer-checked:bg-primary peer-checked:border-primary peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/60 peer-focus:ring-offset-2 peer-focus:ring-offset-background" />
        <div className="absolute left-1 h-4 w-4 rounded-full bg-muted-foreground transition-transform peer-checked:translate-x-5 peer-checked:bg-primary-foreground" />
      </div>
      {label && <span className="text-sm text-foreground">{label}</span>}
    </label>
  );
});

Switch.displayName = "Switch";

export { Switch };





