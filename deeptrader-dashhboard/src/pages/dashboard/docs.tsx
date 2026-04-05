/**
 * Documentation Page
 *
 * Renders platform documentation from the Page_Doc markdown files.
 * Supports deep linking via ?page=/path query parameter.
 */

import { useState, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Book, ChevronRight, Search, FileText } from "lucide-react";
import { Input } from "../../components/ui/input";
import { ScrollArea } from "../../components/ui/scroll-area";
import { cn } from "../../lib/utils";
import { DashBar } from "../../components/DashBar";

interface PageDoc {
  path: string;
  title: string;
  group: string;
  description: string;
}

interface PageDetail extends PageDoc {
  markdown: string;
  widgets: string[];
  modals: string[];
  actions: string[];
  settings: string[];
}

/** Simple markdown-to-HTML renderer for headings, lists, bold, links, code. */
function renderMarkdown(md: string): string {
  return md
    .split("\n")
    .map((line) => {
      // Headings
      if (line.startsWith("### ")) return `<h3 class="text-lg font-semibold mt-6 mb-2">${line.slice(4)}</h3>`;
      if (line.startsWith("## ")) return `<h2 class="text-xl font-bold mt-8 mb-3 pb-2 border-b">${line.slice(3)}</h2>`;
      if (line.startsWith("# ")) return `<h1 class="text-2xl font-bold mb-4">${line.slice(2)}</h1>`;
      // Unordered list
      if (line.startsWith("- ")) {
        const content = line.slice(2)
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/`(.+?)`/g, '<code class="px-1 py-0.5 rounded bg-muted text-sm font-mono">$1</code>')
          .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" class="text-primary underline">$1</a>');
        return `<li class="ml-4 list-disc text-sm leading-relaxed">${content}</li>`;
      }
      // Frontmatter fence
      if (line.trim() === "---") return "";
      // Skip frontmatter lines (key: value)
      if (line.match(/^(path|title|group|description):\s/)) return "";
      // Empty line
      if (!line.trim()) return '<div class="h-3"></div>';
      // Paragraph with inline formatting
      const formatted = line
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`(.+?)`/g, '<code class="px-1 py-0.5 rounded bg-muted text-sm font-mono">$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" class="text-primary underline">$1</a>');
      return `<p class="text-sm leading-relaxed text-muted-foreground">${formatted}</p>`;
    })
    .join("\n");
}

export default function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [pages, setPages] = useState<PageDoc[]>([]);
  const [selectedPage, setSelectedPage] = useState<PageDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const activePath = searchParams.get("page") || "/";

  // Fetch page list
  useEffect(() => {
    fetch("/api/docs/pages")
      .then((r) => r.json())
      .then((data) => {
        setPages(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // Fetch selected page content
  useEffect(() => {
    if (!activePath) return;
    const normalized = activePath.startsWith("/") ? activePath.slice(1) : activePath;
    const endpoint = normalized || "dashboard";
    fetch(`/api/docs/pages/${endpoint}`)
      .then((r) => {
        if (!r.ok) return null;
        return r.json();
      })
      .then((data) => {
        if (data) setSelectedPage(data);
      })
      .catch(() => {});
  }, [activePath]);

  // Group pages
  const grouped = useMemo(() => {
    const groups: Record<string, PageDoc[]> = {};
    const filtered = filter
      ? pages.filter(
          (p) =>
            p.title.toLowerCase().includes(filter.toLowerCase()) ||
            p.description.toLowerCase().includes(filter.toLowerCase())
        )
      : pages;
    for (const p of filtered) {
      (groups[p.group] ??= []).push(p);
    }
    return groups;
  }, [pages, filter]);

  const selectPage = (path: string) => {
    setSearchParams({ page: path });
  };

  return (
    <>
      <DashBar />
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-[280px] shrink-0 border-r bg-card/50 flex flex-col">
          <div className="p-3 border-b">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Filter docs..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-8 h-8 text-sm"
              />
            </div>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-2 space-y-4">
              {loading ? (
                <div className="p-4 text-sm text-muted-foreground">Loading...</div>
              ) : (
                Object.entries(grouped).map(([group, items]) => (
                  <div key={group}>
                    <div className="px-2 py-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {group}
                    </div>
                    {items.map((p) => (
                      <button
                        key={p.path}
                        onClick={() => selectPage(p.path)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors text-left",
                          activePath === p.path
                            ? "bg-primary/10 text-primary font-medium"
                            : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                        )}
                      >
                        <FileText className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{p.title}</span>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </aside>

        {/* Content */}
        <main className="flex-1 overflow-auto">
          {selectedPage ? (
            <div className="max-w-3xl mx-auto p-8">
              {/* Breadcrumb */}
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-6">
                <Book className="h-3.5 w-3.5" />
                <span>Docs</span>
                <ChevronRight className="h-3 w-3" />
                <span>{selectedPage.group}</span>
                <ChevronRight className="h-3 w-3" />
                <span className="text-foreground font-medium">{selectedPage.title}</span>
              </div>

              {/* Description */}
              <p className="text-muted-foreground mb-6">{selectedPage.description}</p>

              {/* Rendered markdown */}
              <div
                className="prose prose-sm dark:prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(selectedPage.markdown) }}
              />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <Book className="h-12 w-12 mb-4 opacity-30" />
              <p className="text-lg font-medium">Platform Documentation</p>
              <p className="text-sm mt-1">Select a topic from the sidebar</p>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
