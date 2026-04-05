import * as React from "react";
import { cn } from "../../lib/utils";
import { ChevronDown, Check } from "lucide-react";

// Context for Select state
interface SelectContextValue {
  value: string;
  onValueChange: (value: string, label?: string) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
  selectedLabel: string;
}

const SelectContext = React.createContext<SelectContextValue | null>(null);

function useSelectContext() {
  const context = React.useContext(SelectContext);
  if (!context) {
    throw new Error("Select components must be used within a Select");
  }
  return context;
}

// Main Select component - Compound component API
interface SelectProps {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  children?: React.ReactNode;  // Optional when using options
  // Backward compatible simple API
  options?: { value: string; label: string }[];
  onChange?: (e: { target: { value: string } }) => void;
}

export function Select({ 
  value: controlledValue, 
  defaultValue = "", 
  onValueChange, 
  children,
  options,
  onChange,
}: SelectProps) {
  const [internalValue, setInternalValue] = React.useState(defaultValue);
  const [selectedLabel, setSelectedLabel] = React.useState("");
  const [open, setOpen] = React.useState(false);

  const value = controlledValue !== undefined ? controlledValue : internalValue;
  
  const handleValueChange = React.useCallback((newValue: string, label?: string) => {
    if (controlledValue === undefined) {
      setInternalValue(newValue);
    }
    if (label) {
      setSelectedLabel(label);
    }
    onValueChange?.(newValue);
    // Also call legacy onChange if provided
    onChange?.({ target: { value: newValue } });
    setOpen(false);
  }, [controlledValue, onValueChange, onChange]);

  // Backward compatible mode: render native select if options prop is provided
  if (options) {
    return (
      <select
        value={value}
        onChange={(e) => handleValueChange(e.target.value)}
        className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  }

  return (
    <SelectContext.Provider value={{ value, onValueChange: handleValueChange, open, setOpen, selectedLabel }}>
      <div className="relative">
        {children}
      </div>
    </SelectContext.Provider>
  );
}

// SelectTrigger
interface SelectTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children?: React.ReactNode;
}

export const SelectTrigger = React.forwardRef<HTMLButtonElement, SelectTriggerProps>(
  ({ className, children, ...props }, ref) => {
    const { open, setOpen } = useSelectContext();

    return (
      <button
        ref={ref}
        type="button"
        role="combobox"
        aria-expanded={open}
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        onClick={() => setOpen(!open)}
        {...props}
      >
        {children}
        <ChevronDown className={cn("h-4 w-4 opacity-50 transition-transform", open && "rotate-180")} />
      </button>
    );
  }
);
SelectTrigger.displayName = "SelectTrigger";

// SelectValue
interface SelectValueProps {
  placeholder?: string;
}

export function SelectValue({ placeholder }: SelectValueProps) {
  const { value, selectedLabel } = useSelectContext();
  
  // Display the label if we have one, otherwise the value
  const displayText = selectedLabel || value;
  
  return (
    <span className={cn(!value && "text-muted-foreground")}>
      {value ? displayText : placeholder}
    </span>
  );
}

// SelectContent
interface SelectContentProps {
  children: React.ReactNode;
  className?: string;
}

export function SelectContent({ children, className }: SelectContentProps) {
  const { open, setOpen } = useSelectContext();
  const ref = React.useRef<HTMLDivElement>(null);

  // Close on click outside
  React.useEffect(() => {
    if (!open) return;
    
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open, setOpen]);

  if (!open) return null;

  return (
    <div
      ref={ref}
      className={cn(
        "absolute z-[100] mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95",
        className
      )}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  );
}

// SelectItem
interface SelectItemProps {
  value: string;
  children: React.ReactNode;
  className?: string;
}

export function SelectItem({ value: itemValue, children, className }: SelectItemProps) {
  const { value, onValueChange } = useSelectContext();
  const isSelected = value === itemValue;
  
  // Get text content from children for the label
  const getTextContent = (node: React.ReactNode): string => {
    if (typeof node === 'string') return node;
    if (typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(getTextContent).join('');
    if (React.isValidElement(node)) {
      const props = node.props as { children?: React.ReactNode };
      if (props.children) {
        return getTextContent(props.children);
      }
    }
    return '';
  };
  
  const label = getTextContent(children);

  return (
    <div
      role="option"
      aria-selected={isSelected}
      data-select-value={itemValue}
      className={cn(
        "relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground",
        isSelected && "bg-accent/50",
        className
      )}
      onClick={() => onValueChange(itemValue, label)}
    >
      <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
        {isSelected && <Check className="h-4 w-4" />}
      </span>
      {children}
    </div>
  );
}

// SelectGroup (for grouping items)
interface SelectGroupProps {
  children: React.ReactNode;
}

export function SelectGroup({ children }: SelectGroupProps) {
  return <div className="py-1">{children}</div>;
}

// SelectLabel (for group labels)
interface SelectLabelProps {
  children: React.ReactNode;
  className?: string;
}

export function SelectLabel({ children, className }: SelectLabelProps) {
  return (
    <div className={cn("px-2 py-1.5 text-xs font-semibold text-muted-foreground", className)}>
      {children}
    </div>
  );
}

// SelectSeparator
export function SelectSeparator() {
  return <div className="-mx-1 my-1 h-px bg-muted" />;
}
