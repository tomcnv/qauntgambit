import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Search, FileText, ArrowRight } from "lucide-react";
import { Dialog, DialogContent } from "./ui/dialog";
import { Input } from "./ui/input";
import { cn } from "../lib/utils";

// NAV_GROUPS duplicated here for search — keeps component self-contained
const PAGE_ITEMS = [
  { label: "Overview", path: "/", group: "Trading", description: "Mission control + fleet" },
  { label: "Live", path: "/live", group: "Trading", description: "Active bot status & controls" },
  { label: "Orders & Fills", path: "/orders", group: "Trading", description: "Fill rate, latency, rejects" },
  { label: "Positions", path: "/positions", group: "Trading", description: "Open positions & exposure" },
  { label: "Trade History", path: "/history", group: "Trading", description: "All trades, filterable" },
  { label: "Limits & Guardrails", path: "/risk/limits", group: "Risk", description: "Live controls" },
  { label: "Exposure", path: "/risk/exposure", group: "Risk", description: "Current & historical" },
  { label: "VaR & Stress Tests", path: "/risk/metrics", group: "Risk", description: "VaR, ES, scenarios" },
  { label: "Incidents", path: "/risk/incidents", group: "Risk", description: "Breaches & post-mortems" },
  { label: "Pipeline Health", path: "/pipeline-health", group: "Analysis", description: "Engine layers & latency" },
  { label: "Replay Studio", path: "/analysis/replay", group: "Analysis", description: "Decision forensics & replay" },
  { label: "Market Context", path: "/market-context", group: "Analysis", description: "Regime & conditions" },
  { label: "Signals", path: "/signals", group: "Analysis", description: "Signal health & features" },
  { label: "Execution", path: "/execution", group: "Analysis", description: "TCA, slippage, latency" },
  { label: "Backtesting", path: "/backtesting", group: "Research", description: "Run & analyze backtests" },
  { label: "Model Training", path: "/analysis/model-training", group: "Research", description: "Train and review ONNX models" },
  { label: "Data Quality", path: "/data-quality", group: "Research", description: "Feed health & gaps" },
  { label: "Exchange Accounts", path: "/exchange-accounts", group: "System", description: "Venue connections & risk pools" },
  { label: "Bot Management", path: "/bot-management", group: "System", description: "Fleet ops & bot builder" },
  { label: "Profiles", path: "/profiles", group: "System", description: "Strategy profiles" },
  { label: "Settings", path: "/settings", group: "System", description: "Global configuration" },
  { label: "Runtime Config", path: "/settings/runtime-config", group: "System", description: "Live runtime knobs" },
  { label: "Audit Log", path: "/audit", group: "System", description: "Change history" },
];

export interface DocSearchResult {
  path: string;
  title: string;
  section: string;
  snippet: string;
  score: number;
}

export function CommandPalette({ open: externalOpen, onOpenChange }: { open?: boolean; onOpenChange?: (open: boolean) => void } = {}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = externalOpen ?? internalOpen;
  const setOpen = (v: boolean) => {
    setInternalOpen(v);
    onOpenChange?.(v);
  };
  const [query, setQuery] = useState("");
  const [docResults, setDocResults] = useState<DocSearchResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Keyboard shortcut: ⌘K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  // Focus input when dialog opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery("");
      setDocResults([]);
      setSelectedIndex(0);
    }
  }, [open]);

  // Debounced doc search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setDocResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/docs/search?q=${encodeURIComponent(query)}&limit=5`);
        if (res.ok) {
          const data = await res.json();
          setDocResults(data.results || []);
        }
      } catch {
        // Search unavailable — silently degrade
      }
    }, 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // Filter pages by query
  const filteredPages = query.trim()
    ? PAGE_ITEMS.filter(
        (p) =>
          p.label.toLowerCase().includes(query.toLowerCase()) ||
          p.description.toLowerCase().includes(query.toLowerCase()) ||
          p.group.toLowerCase().includes(query.toLowerCase())
      )
    : PAGE_ITEMS;

  // Combined results for keyboard navigation
  const allResults = [
    ...filteredPages.map((p) => ({ type: "page" as const, ...p })),
    ...docResults.map((d) => ({ type: "doc" as const, ...d })),
  ];

  const handleSelect = useCallback(
    (item: (typeof allResults)[number]) => {
      setOpen(false);
      if (item.type === "doc") {
        navigate(`/docs?page=${encodeURIComponent(item.path)}`);
      } else {
        navigate(item.path);
      }
    },
    [navigate]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, allResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && allResults[selectedIndex]) {
      e.preventDefault();
      handleSelect(allResults[selectedIndex]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="p-0 overflow-hidden" data-testid="command-palette-dialog">
        <div className="flex items-center border-b px-3" data-testid="command-palette-search">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, documentation, actions..."
            className="border-0 focus-visible:ring-0 focus-visible:ring-offset-0"
            data-testid="command-palette-input"
          />
        </div>

        <div className="max-h-[300px] overflow-y-auto p-2" data-testid="command-palette-results">
          {/* Pages category */}
          {filteredPages.length > 0 && (
            <div>
              <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground" data-testid="pages-category">
                Pages
              </div>
              {filteredPages.map((page, i) => (
                <button
                  key={page.path}
                  onClick={() => handleSelect({ type: "page", ...page })}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
                    selectedIndex === i
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/50"
                  )}
                  data-testid={`page-result-${page.path}`}
                >
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex flex-col items-start">
                    <span className="font-medium">{page.label}</span>
                    <span className="text-xs text-muted-foreground">{page.description}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Documentation category */}
          {docResults.length > 0 && (
            <div>
              <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground" data-testid="documentation-category">
                Documentation
              </div>
              {docResults.map((doc, i) => (
                <button
                  key={`${doc.path}-${doc.section}`}
                  onClick={() => handleSelect({ type: "doc", ...doc })}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
                    selectedIndex === filteredPages.length + i
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/50"
                  )}
                  data-testid={`doc-result-${doc.path}`}
                >
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex flex-col items-start">
                    <span className="font-medium">{doc.title}</span>
                    <span className="text-xs text-muted-foreground">{doc.section}: {doc.snippet}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {allResults.length === 0 && query.trim() && (
            <div className="px-2 py-6 text-center text-sm text-muted-foreground" data-testid="no-results">
              No results found for "{query}"
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
