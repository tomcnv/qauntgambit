import { AnimatedSection } from "@/components/AnimatedSection";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const architectureDetails = [
  {
    id: "command-bus",
    title: "Command bus / throttling",
    content: "Dedicated command bus for symbol-level throttling. Rate limits are monitored and respected automatically with graceful degradation.",
  },
  {
    id: "snapshotting",
    title: "State snapshotting",
    content: "Redis-mirrored state snapshots for cold observers. Real-time state available to dashboards without impacting hot path latency.",
  },
  {
    id: "wal-replay",
    title: "WAL / replay parity",
    content: "WAL streaming with S3 parity for forensic replay. Every decision is replayable with exact state reconstruction.",
  },
  {
    id: "storage",
    title: "Storage & retention",
    content: "Tiered storage with configurable retention policies. Hot data in Redis, warm in Postgres, cold in S3 with full query capability.",
  },
];

export function ArchitectureSection() {
  return (
    <section id="architecture" className="relative border-0 py-32 lg:py-40 section-dark overflow-hidden">
      {/* Diagonal top */}
      <div className="absolute top-0 left-0 right-0 h-24 bg-background" style={{ clipPath: 'polygon(0 0, 100% 0, 100% 100%, 0 0)' }} />
      
      {/* Background pattern */}
      <div className="absolute inset-0 bg-dot-pattern-light opacity-40 pointer-events-none" />

      <div className="container mx-auto px-4 lg:px-8 relative z-10">
        <AnimatedSection animation="fade-up" className="text-center mb-16">
          <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
            Architecture
          </p>
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold mb-6">
            Designed for latency + forensic clarity
          </h2>
          <p className="text-lg text-[hsl(215,20%,65%)] max-w-2xl mx-auto">
            Decouple latency-critical services from analytic workloads.
          </p>
        </AnimatedSection>

        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16">
          {/* Left: Two-column diagram */}
          <AnimatedSection animation="fade-up" delay={100}>
            <div className="bg-[hsl(222,47%,13%)] rounded-2xl p-8 border border-[hsl(222,47%,20%)]">
              <div className="grid grid-cols-2 gap-6">
                {/* Hot Path */}
                <div>
                  <div className="flex items-center gap-3 mb-6">
                    <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-sm font-mono font-bold text-emerald-400">HOT PATH</span>
                  </div>

                  <div className="relative">
                    {/* Continuous vertical line */}
                    <div className="absolute left-[11px] top-3 bottom-3 w-px bg-emerald-400/50" />

                    <div className="space-y-4">
                      {["Market Data", "Features", "Signals", "Risk Gates", "Execution"].map((item) => (
                        <div key={item} className="flex items-center gap-3 relative">
                          <div className="w-6 h-6 rounded-full border-2 border-emerald-400 bg-[hsl(222,47%,13%)] flex items-center justify-center z-10">
                            <div className="w-2 h-2 rounded-full bg-emerald-400" />
                          </div>
                          <span className="text-sm font-mono text-[hsl(210,40%,90%)]">{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="pt-4 mt-4 border-t border-[hsl(222,47%,25%)]">
                    <span className="text-xs text-[hsl(215,20%,55%)]">{"<"}210µs median</span>
                  </div>
                </div>

                {/* Cold Path */}
                <div>
                  <div className="flex items-center gap-3 mb-6">
                    <div className="w-3 h-3 rounded-full bg-[hsl(215,20%,45%)]" />
                    <span className="text-sm font-mono font-bold text-[hsl(215,20%,65%)]">COLD PATH</span>
                  </div>

                  <div className="relative">
                    {/* Continuous vertical line */}
                    <div className="absolute left-[11px] top-3 bottom-3 w-px bg-[hsl(215,20%,35%)]" />

                    <div className="space-y-4">
                      {["State Publisher", "Telemetry", "WAL Streaming", "S3 Archive", "Replay"].map((item) => (
                        <div key={item} className="flex items-center gap-3 relative">
                          <div className="w-6 h-6 rounded-full border-2 border-[hsl(215,20%,35%)] bg-[hsl(222,47%,13%)] flex items-center justify-center z-10">
                            <div className="w-2 h-2 rounded-full bg-[hsl(215,20%,45%)]" />
                          </div>
                          <span className="text-sm font-mono text-[hsl(215,20%,65%)]">{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="pt-4 mt-4 border-t border-[hsl(222,47%,25%)]">
                    <span className="text-xs text-[hsl(215,20%,55%)]">async, durable</span>
                  </div>
                </div>
              </div>
            </div>
          </AnimatedSection>

          {/* Right: Accordion for details */}
          <AnimatedSection animation="fade-up" delay={200}>
            <div className="bg-[hsl(222,47%,13%)] rounded-2xl p-8 border border-[hsl(222,47%,18%)]">
              <h3 className="text-xl font-display font-semibold mb-6">
                Technical details
              </h3>
              <Accordion type="single" collapsible className="w-full">
                {architectureDetails.map((detail, idx) => (
                  <AccordionItem key={detail.id} value={detail.id} className="border-[hsl(222,47%,20%)]">
                    <AccordionTrigger className="text-left font-medium hover:text-primary transition-colors">
                      {detail.title}
                    </AccordionTrigger>
                    <AccordionContent className="text-[hsl(215,20%,65%)] leading-relaxed">
                      {detail.content}
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </div>
          </AnimatedSection>
        </div>
      </div>

      {/* Diagonal bottom */}
      <div className="absolute bottom-0 left-0 right-0 h-24 bg-background" style={{ clipPath: 'polygon(0 0, 100% 100%, 100% 100%, 0 100%)' }} />
    </section>
  );
}
