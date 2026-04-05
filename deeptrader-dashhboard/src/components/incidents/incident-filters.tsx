import { useState, useMemo } from "react";
import {
  Filter,
  X,
  Search,
  Calendar as CalendarIcon,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  format,
  subDays,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  addMonths,
  startOfYear,
  parseISO,
  isSameDay,
  isSameMonth,
  isWithinInterval,
} from "date-fns";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import { Checkbox } from "../ui/checkbox";
import { Label } from "../ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Separator } from "../ui/separator";
import { cn } from "../../lib/utils";

export interface IncidentFiltersState {
  severity?: string[];
  status?: string[];
  incidentType?: string[];
  triggerRule?: string;
  search?: string;
  startDate?: string;
  endDate?: string;
  causedPause?: boolean;
}

interface IncidentFiltersProps {
  filters: IncidentFiltersState;
  onFiltersChange: (filters: IncidentFiltersState) => void;
}

const SEVERITY_OPTIONS = [
  { value: "critical", label: "Critical", color: "text-red-500 bg-red-500/10" },
  { value: "high", label: "High", color: "text-orange-500 bg-orange-500/10" },
  { value: "medium", label: "Medium", color: "text-amber-500 bg-amber-500/10" },
  { value: "low", label: "Low", color: "text-blue-500 bg-blue-500/10" },
];

const STATUS_OPTIONS = [
  { value: "open", label: "Open", color: "text-red-500" },
  { value: "acknowledged", label: "Acknowledged", color: "text-amber-500" },
  { value: "investigating", label: "Investigating", color: "text-blue-500" },
  { value: "mitigated", label: "Mitigated", color: "text-cyan-500" },
  { value: "resolved", label: "Resolved", color: "text-emerald-500" },
  { value: "closed", label: "Closed", color: "text-muted-foreground" },
];

const TYPE_OPTIONS = [
  { value: "daily_loss_breach", label: "Daily Loss Breach" },
  { value: "drawdown_breach", label: "Drawdown Breach" },
  { value: "exposure_breach", label: "Exposure Breach" },
  { value: "leverage_breach", label: "Leverage Breach" },
  { value: "rapid_loss", label: "Rapid Loss" },
  { value: "fill_rate_degraded", label: "Fill Rate Degraded" },
  { value: "connectivity_loss", label: "Connectivity Loss" },
  { value: "slippage_spike", label: "Slippage Spike" },
  { value: "reconciliation_failure", label: "Reconciliation Failure" },
  { value: "manual_pause", label: "Manual Pause" },
  { value: "kill_switch", label: "Kill Switch" },
];

const TIME_PRESETS = [
  { key: "all", label: "All", getRange: () => ({ start: "", end: "" }) },
  { key: "today", label: "Today", getRange: () => ({ start: format(new Date(), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
  { key: "24h", label: "24h", getRange: () => ({ start: format(subDays(new Date(), 1), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
  { key: "7d", label: "7d", getRange: () => ({ start: format(subDays(new Date(), 7), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
  { key: "30d", label: "30d", getRange: () => ({ start: format(subDays(new Date(), 30), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
  { key: "mtd", label: "MTD", getRange: () => ({ start: format(startOfMonth(new Date()), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
  { key: "ytd", label: "YTD", getRange: () => ({ start: format(startOfYear(new Date()), "yyyy-MM-dd"), end: format(new Date(), "yyyy-MM-dd") }) },
];

// Range Calendar Component
function RangeCalendar({
  month,
  startDate,
  endDate,
  onMonthChange,
  onSelectDate,
}: {
  month: Date;
  startDate: string;
  endDate: string;
  onMonthChange: (next: Date) => void;
  onSelectDate: (date: string) => void;
}) {
  const monthStart = startOfMonth(month);
  const monthEnd = endOfMonth(month);
  const startDateObj = startDate ? parseISO(startDate) : null;
  const endDateObj = endDate ? parseISO(endDate) : null;

  const weeks: Date[][] = [];
  let current = startOfWeek(monthStart, { weekStartsOn: 1 });
  const end = endOfWeek(monthEnd, { weekStartsOn: 1 });

  while (current <= end) {
    const week: Date[] = [];
    for (let i = 0; i < 7; i++) {
      week.push(current);
      current = addDays(current, 1);
    }
    weeks.push(week);
  }

  const isInRange = (date: Date) => {
    if (!startDateObj || !endDateObj) return false;
    return isWithinInterval(date, {
      start: startDateObj < endDateObj ? startDateObj : endDateObj,
      end: startDateObj < endDateObj ? endDateObj : startDateObj,
    });
  };

  return (
    <div className="p-2">
      <div className="flex items-center justify-between mb-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => onMonthChange(addMonths(month, -1))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm font-medium">{format(month, "MMMM yyyy")}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => onMonthChange(addMonths(month, 1))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-xs text-muted-foreground mb-1">
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => (
          <div key={d} className="py-1">{d}</div>
        ))}
      </div>
      {weeks.map((week, i) => (
        <div key={i} className="grid grid-cols-7 gap-0.5">
          {week.map((day) => {
            const iso = format(day, "yyyy-MM-dd");
            const isStart = startDateObj && isSameDay(day, startDateObj);
            const isEnd = endDateObj && isSameDay(day, endDateObj);
            const inRange = isInRange(day);
            const isCurrentMonth = isSameMonth(day, month);

            return (
              <button
                key={iso}
                onClick={() => onSelectDate(iso)}
                className={cn(
                  "h-7 w-7 text-xs rounded transition-colors",
                  !isCurrentMonth && "text-muted-foreground/40",
                  isCurrentMonth && "hover:bg-muted",
                  inRange && !isStart && !isEnd && "bg-primary/10",
                  (isStart || isEnd) && "bg-primary text-primary-foreground",
                )}
              >
                {format(day, "d")}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function IncidentFilters({ filters, onFiltersChange }: IncidentFiltersProps) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [dateRangeOpen, setDateRangeOpen] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState(new Date());
  const [tempStartDate, setTempStartDate] = useState(filters.startDate || "");
  const [tempEndDate, setTempEndDate] = useState(filters.endDate || "");

  // Determine active time preset
  const activePreset = useMemo(() => {
    if (!filters.startDate && !filters.endDate) return "all";
    for (const preset of TIME_PRESETS) {
      const range = preset.getRange();
      if (filters.startDate === range.start && filters.endDate === range.end) {
        return preset.key;
      }
    }
    return "custom";
  }, [filters.startDate, filters.endDate]);

  const updateFilters = (updates: Partial<IncidentFiltersState>) => {
    onFiltersChange({ ...filters, ...updates });
  };

  const toggleArrayFilter = (
    key: "severity" | "status" | "incidentType",
    value: string
  ) => {
    const current = filters[key] || [];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    updateFilters({ [key]: updated.length > 0 ? updated : undefined });
  };

  const clearAllFilters = () => {
    // Keep the 7-day default when clearing
    const range = TIME_PRESETS.find(p => p.key === "7d")!.getRange();
    onFiltersChange({
      startDate: range.start,
      endDate: range.end,
    });
    setTempStartDate(range.start);
    setTempEndDate(range.end);
    setFiltersOpen(false);
    setDateRangeOpen(false);
  };

  const applyTimePreset = (preset: typeof TIME_PRESETS[0]) => {
    const range = preset.getRange();
    updateFilters({ startDate: range.start || undefined, endDate: range.end || undefined });
    setTempStartDate(range.start);
    setTempEndDate(range.end);
  };

  const handleSelectDate = (iso: string) => {
    if (!tempStartDate || (tempStartDate && tempEndDate)) {
      setTempStartDate(iso);
      setTempEndDate("");
    } else {
      const start = parseISO(tempStartDate);
      const selected = parseISO(iso);
      if (selected < start) {
        setTempEndDate(tempStartDate);
        setTempStartDate(iso);
      } else {
        setTempEndDate(iso);
      }
    }
  };

  const applyDateRange = () => {
    updateFilters({
      startDate: tempStartDate || undefined,
      endDate: tempEndDate || undefined,
    });
    setDateRangeOpen(false);
  };

  const toggleFilters = () => {
    setFiltersOpen((o) => {
      if (!o) setDateRangeOpen(false);
      return !o;
    });
  };

  const toggleDateRange = () => {
    setDateRangeOpen((o) => {
      if (!o) setFiltersOpen(false);
      return !o;
    });
  };

  const activeFilterCount =
    (filters.severity?.length || 0) +
    (filters.status?.length || 0) +
    (filters.incidentType?.length || 0) +
    (filters.search ? 1 : 0) +
    (filters.causedPause ? 1 : 0);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Search */}
      <div className="relative flex-1 min-w-[180px] max-w-[250px]">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search..."
          value={filters.search || ""}
          onChange={(e) => updateFilters({ search: e.target.value || undefined })}
          className="pl-8 h-8 text-sm"
        />
      </div>

      {/* Filter Button with Dropdown */}
      <DropdownMenu open={filtersOpen} onOpenChange={setFiltersOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className={cn("h-8 gap-1", activeFilterCount > 0 && "text-primary")}
            onClick={toggleFilters}
          >
            <Filter className="h-4 w-4" />
            {activeFilterCount > 0 && (
              <Badge variant="default" className="h-5 px-1 text-xs">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-80 p-4">
          <div className="space-y-4">
            {/* Severity */}
            <div>
              <Label className="text-xs font-medium text-muted-foreground uppercase">Severity</Label>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {SEVERITY_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    onClick={() => toggleArrayFilter("severity", option.value)}
                    className={cn(
                      "px-2 py-1 text-xs rounded border transition-colors",
                      filters.severity?.includes(option.value)
                        ? option.color + " border-current"
                        : "border-border hover:bg-muted"
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            {/* Status */}
            <div>
              <Label className="text-xs font-medium text-muted-foreground uppercase">Status</Label>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {STATUS_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    onClick={() => toggleArrayFilter("status", option.value)}
                    className={cn(
                      "px-2 py-1 text-xs rounded border transition-colors",
                      filters.status?.includes(option.value)
                        ? "bg-primary/10 border-primary text-primary"
                        : "border-border hover:bg-muted"
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            {/* Type */}
            <div>
              <Label className="text-xs font-medium text-muted-foreground uppercase">Incident Type</Label>
              <div className="grid grid-cols-2 gap-2 mt-2 max-h-[150px] overflow-y-auto">
                {TYPE_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex items-center gap-2 text-xs cursor-pointer"
                  >
                    <Checkbox
                      checked={filters.incidentType?.includes(option.value)}
                      onCheckedChange={() => toggleArrayFilter("incidentType", option.value)}
                    />
                    <span className="truncate">{option.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <Separator />

            {/* Caused Pause */}
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={filters.causedPause || false}
                onCheckedChange={(checked) => updateFilters({ causedPause: checked ? true : undefined })}
              />
              <span className="text-sm">Only incidents that paused trading</span>
            </label>

            <Separator />

            {/* Clear Button */}
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                onClick={clearAllFilters}
              >
                <X className="h-4 w-4 mr-1" />
                Clear All
              </Button>
            </div>
          </div>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Time Preset Buttons */}
      <div className="flex rounded-lg border bg-muted/50 p-0.5">
        {TIME_PRESETS.map((preset) => (
          <Button
            key={preset.key}
            variant={activePreset === preset.key ? "default" : "ghost"}
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => applyTimePreset(preset)}
          >
            {preset.label}
          </Button>
        ))}
      </div>

      {/* Custom Date Range Button + Dropdown */}
      <DropdownMenu open={dateRangeOpen} onOpenChange={setDateRangeOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            variant={activePreset === "custom" ? "default" : "ghost"}
            size="sm"
            className="h-7 gap-1 text-xs"
            onClick={toggleDateRange}
          >
            <CalendarIcon className="h-3.5 w-3.5" />
            {activePreset === "custom" && filters.startDate && filters.endDate ? (
              <span>
                {format(parseISO(filters.startDate), "MMM d")} - {format(parseISO(filters.endDate), "MMM d")}
              </span>
            ) : (
              <span>Custom</span>
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto p-0">
          <RangeCalendar
            month={calendarMonth}
            startDate={tempStartDate}
            endDate={tempEndDate}
            onMonthChange={setCalendarMonth}
            onSelectDate={handleSelectDate}
          />
          <Separator />
          <div className="p-2 flex items-center justify-between">
            <div className="text-xs text-muted-foreground">
              {tempStartDate && tempEndDate ? (
                <>
                  {format(parseISO(tempStartDate), "MMM d, yyyy")} →{" "}
                  {format(parseISO(tempEndDate), "MMM d, yyyy")}
                </>
              ) : tempStartDate ? (
                <>Select end date</>
              ) : (
                <>Select start date</>
              )}
            </div>
            <Button
              size="sm"
              className="h-7"
              onClick={applyDateRange}
              disabled={!tempStartDate || !tempEndDate}
            >
              Apply
            </Button>
          </div>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Clear all if filters active */}
      {activeFilterCount > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs text-muted-foreground"
          onClick={clearAllFilters}
        >
          <X className="h-3.5 w-3.5 mr-1" />
          Clear
        </Button>
      )}
    </div>
  );
}

export default IncidentFilters;
