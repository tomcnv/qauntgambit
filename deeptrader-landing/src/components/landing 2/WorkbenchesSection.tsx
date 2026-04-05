import { useState } from "react";
import { AnimatedSection } from "@/components/AnimatedSection";
import { workbenchTabs } from "@/data/landingContent";
import { cn } from "@/lib/utils";
import dashboardOverview from "@/assets/dashboard-overview.png";
import dashboardSignals from "@/assets/dashboard-signals.png";
import dashboardReplay from "@/assets/dashboard-replay.png";

const tabScreenshots: Record<string, string> = {
  "trading-ops": dashboardOverview,
  "signals": dashboardSignals,
  "allocator": dashboardOverview,
  "risk": dashboardSignals,
  "replay": dashboardReplay,
};

export function WorkbenchesSection() {
  const [activeTab, setActiveTab] = useState("trading-ops");

  const activeWorkbench = workbenchTabs.find((tab) => tab.id === activeTab);

  return (
    <section id="workbenches" className="py-24 lg:py-32 bg-background">
      <div className="container mx-auto px-4 lg:px-8">
        <AnimatedSection animation="fade-up" className="text-center mb-12">
          <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
            Workbenches
          </p>
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-4">
            Specialized control surfaces
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-2">
            Different roles need different control surfaces.
          </p>
          <p className="text-muted-foreground max-w-2xl mx-auto">
            Each domain gets its own purpose-built interface.
          </p>
        </AnimatedSection>

        {/* Tabs */}
        <AnimatedSection animation="fade-up" delay={100}>
          <div className="flex flex-wrap justify-center gap-2 mb-8">
            {workbenchTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "px-5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                  activeTab === tab.id
                    ? "bg-primary text-primary-foreground shadow-lg shadow-primary/25"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {tab.title}
              </button>
            ))}
          </div>
        </AnimatedSection>

        {/* Content */}
        <AnimatedSection animation="fade-up" delay={200}>
          <div className="grid lg:grid-cols-5 gap-8 lg:gap-12 items-start">
            {/* Screenshot - 3 cols */}
            <div className="lg:col-span-3">
              <div className="relative rounded-2xl overflow-hidden border border-border bg-card shadow-2xl">
                {/* Browser chrome */}
                <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-muted/30">
                  <div className="flex gap-1.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                  </div>
                  <div className="flex-1 flex justify-center">
                    <span className="text-xs text-muted-foreground font-mono">{activeWorkbench?.title}</span>
                  </div>
                </div>
                
                {/* Screenshot */}
                <div className="relative aspect-[16/10] overflow-hidden">
                  {workbenchTabs.map((tab) => (
                    <img
                      key={tab.id}
                      src={tabScreenshots[tab.id]}
                      alt={`${tab.title} workbench`}
                      className={cn(
                        "absolute inset-0 w-full h-full object-cover object-top transition-opacity duration-500",
                        activeTab === tab.id ? "opacity-100" : "opacity-0"
                      )}
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Bullets - 2 cols */}
            <div className="lg:col-span-2 space-y-6">
              <div>
                <h3 className="text-2xl font-display font-semibold text-foreground mb-4">
                  {activeWorkbench?.title}
                </h3>
                {activeWorkbench?.description && (
                  <p className="text-muted-foreground mb-4">
                    {activeWorkbench.description}
                  </p>
                )}
                {activeWorkbench?.persona && (
                  <p className="text-sm text-primary font-medium mb-6">
                    Best for: {activeWorkbench.persona}
                  </p>
                )}
                <ul className="space-y-4">
                  {activeWorkbench?.bullets.map((bullet, idx) => (
                    <li key={idx} className="flex items-start gap-4">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold mt-0.5">
                        {idx + 1}
                      </span>
                      <span className="text-muted-foreground">{bullet}</span>
                    </li>
                  ))}
                </ul>
              </div>
              
              {(activeWorkbench?.keyMetric || activeWorkbench?.secondaryMetric) && (
                <div className="pt-6 border-t border-border grid grid-cols-2 gap-4">
                  {activeWorkbench?.keyMetric && (
                    <div>
                      <span className="text-xs text-muted-foreground uppercase tracking-wider">Key metric</span>
                      <p className="text-lg font-display font-semibold text-foreground mt-1">
                        {activeWorkbench.keyMetric}
                      </p>
                    </div>
                  )}
                  {activeWorkbench?.secondaryMetric && (
                    <div>
                      <span className="text-xs text-muted-foreground uppercase tracking-wider">Also tracks</span>
                      <p className="text-lg font-display font-semibold text-foreground mt-1">
                        {activeWorkbench.secondaryMetric}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </AnimatedSection>
      </div>
    </section>
  );
}
