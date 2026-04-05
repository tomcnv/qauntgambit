import { ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/utils";

type DialogProps = {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
};

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || !open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      <div
        className="absolute inset-0 bg-black/70"
        onClick={() => onOpenChange?.(false)}
        aria-hidden="true"
      />
      <div 
        className="relative z-10 flex w-full items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body
  );
}

type DialogContentProps = {
  children: ReactNode;
  className?: string;
};

export function DialogContent({ children, className }: DialogContentProps) {
  return (
    <div
      className={cn(
        "w-full rounded-2xl border border-border bg-card p-6 shadow-2xl shadow-black/40",
        className
      )}
    >
      {children}
    </div>
  );
}

type DialogSectionProps = {
  children: ReactNode;
  className?: string;
};

export function DialogHeader({ children, className }: DialogSectionProps) {
  return <div className={cn("space-y-1.5", className)}>{children}</div>;
}

export function DialogTitle({ children, className }: DialogSectionProps) {
  return <h3 className={cn("text-lg font-semibold text-foreground", className)}>{children}</h3>;
}

export function DialogDescription({ children, className }: DialogSectionProps) {
  return <p className={cn("text-sm text-muted-foreground", className)}>{children}</p>;
}

export function DialogFooter({ children, className }: DialogSectionProps) {
  return <div className={cn("mt-4 flex items-center gap-3", className)}>{children}</div>;
}


