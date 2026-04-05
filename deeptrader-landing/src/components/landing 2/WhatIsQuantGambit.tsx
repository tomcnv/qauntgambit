import { useState, useEffect, useRef } from "react";
import { AnimatedSection } from "@/components/AnimatedSection";
import { GitBranch, Search, Shield, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

const proofBullets = [
  {
    icon: GitBranch,
    title: "Versioned profiles + diffs",
    description: "Know what changed",
  },
  {
    icon: Search,
    title: "Decision traces (accept + reject)",
    description: "Know why it traded or didn't",
  },
  {
    icon: Shield,
    title: "Risk gates + replay",
    description: "Operate safely, debug fast",
  },
];

const pipelineSteps = [
  {
    id: "market-data",
    label: "Market Data",
    microCopy: "Ticks, candles, venues",
    outputs: ["Raw ticks", "OHLCV candles", "Order book snapshots"],
  },
  {
    id: "features",
    label: "Features",
    microCopy: "Regime, microstructure",
    outputs: ["Volatility regimes", "Spread metrics", "Momentum signals"],
  },
  {
    id: "signals",
    label: "Signals",
    microCopy: "Entries/exits + confidence",
    outputs: ["Entry signals", "Exit signals", "Confidence scores"],
  },
  {
    id: "risk-gates",
    label: "Risk Gates",
    microCopy: "Limits, throttles, kill switch",
    outputs: ["Position limits", "Exposure checks", "Gate decisions"],
    isGate: true,
  },
  {
    id: "execution",
    label: "Execution",
    microCopy: "Orders + fills",
    outputs: ["Orders", "Fills", "Slippage metrics"],
  },
  {
    id: "telemetry",
    label: "Telemetry / Replay",
    microCopy: "Traces + incident playback",
    outputs: ["Decision traces", "Audit log", "Replay sessions", "TCA metrics"],
  },
];

export function WhatIsQuantGambit() {
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [hasAnimated, setHasAnimated] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);
  const sectionRef = useRef<HTMLDivElement>(null);

  // Observe when section comes into view
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasAnimated) {
            setHasAnimated(true);
            runSequentialAnimation();
          }
        });
      },
      { threshold: 0.3 }
    );

    if (sectionRef.current) {
      observer.observe(sectionRef.current);
    }

    return () => observer.disconnect();
  }, [hasAnimated]);

  const runSequentialAnimation = () => {
    setIsAnimating(true);
    
    pipelineSteps.forEach((step, index) => {
      setTimeout(() => {
        setActiveStep(step.id);
        
        // After the last step, settle on "telemetry" (the differentiator)
        if (index === pipelineSteps.length - 1) {
          setTimeout(() => {
            setIsAnimating(false);
            setActiveStep("telemetry");
          }, 400);
        }
      }, index * 800);
    });
  };

  return (
    <section ref={sectionRef} id="product" className="py-24 lg:py-32 bg-background">
      <div className="container mx-auto px-4 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-20 items-start">
          {/* Left: Narrative */}
          <AnimatedSection animation="fade-up">
            <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
              What is QuantGambit
            </p>
            <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-3 leading-tight">
              From signal to execution—with traceability
            </h2>
            <p className="text-lg text-muted-foreground mb-8">
              A control plane for systematic crypto execution.
            </p>
            <p className="text-muted-foreground leading-relaxed mb-8">
              QuantGambit connects your exchange environment, your strategy profiles, and your operational telemetry—so teams can deploy capital with clarity and control.
            </p>

            {/* Proof bullets */}
            <div className="space-y-4 mb-8">
              {proofBullets.map((bullet) => (
                <div key={bullet.title} className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <bullet.icon className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <span className="text-sm font-medium text-foreground">{bullet.title}</span>
                    <span className="text-sm text-muted-foreground ml-2">— {bullet.description}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Payoff line */}
            <p className="text-sm font-medium text-foreground mb-6 border-l-2 border-primary pl-4">
              When something breaks, you don't guess — you inspect.
            </p>

            {/* CTA link */}
            <a
              href="#workbenches"
              className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:text-primary/80 transition-colors group"
            >
              Explore the workbenches
              <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
            </a>
          </AnimatedSection>

          {/* Right: Interactive Pipeline Diagram */}
          <AnimatedSection animation="fade-up" delay={100}>
            <div className="relative bg-card rounded-2xl p-6 lg:p-8 border border-border shadow-sm">
              {/* Pipeline flow */}
              <div className="relative">
                {/* Continuous vertical line */}
                <div className="absolute left-[15px] top-4 bottom-4 w-px bg-border" />

                <div className="space-y-3">
                  {pipelineSteps.map((step) => {
                    const isActive = activeStep === step.id;
                    const isGateActive = step.isGate && isActive;

                    return (
                      <div
                        key={step.id}
                        className="flex items-center gap-4 cursor-pointer group"
                        onMouseEnter={() => !isAnimating && setActiveStep(step.id)}
                      >
                        {/* Node */}
                        <div
                          className={cn(
                            "relative z-10 w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-200",
                            isActive
                              ? isGateActive
                                ? "border-amber-500 bg-amber-500/20"
                                : "border-primary bg-primary/20"
                              : "border-border bg-card"
                          )}
                        >
                          <div
                            className={cn(
                              "w-2.5 h-2.5 rounded-full transition-all duration-200",
                              isActive
                                ? isGateActive
                                  ? "bg-amber-500"
                                  : "bg-primary"
                                : "bg-muted-foreground/30"
                            )}
                          />
                        </div>

                        {/* Label + micro-copy */}
                        <div
                          className={cn(
                            "flex-1 px-4 py-3 rounded-lg border transition-all duration-200",
                            isActive
                              ? isGateActive
                                ? "border-amber-500/30 bg-amber-500/10"
                                : "border-primary/30 bg-primary/10"
                              : "border-border bg-muted/30 group-hover:bg-muted/50"
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span
                              className={cn(
                                "text-sm font-mono font-medium transition-colors",
                                isActive
                                  ? isGateActive
                                    ? "text-amber-600 dark:text-amber-400"
                                    : "text-primary"
                                  : "text-foreground"
                              )}
                            >
                              {step.label}
                            </span>
                          </div>
                          <p
                            className={cn(
                              "text-xs mt-1 transition-colors",
                              isActive ? "text-muted-foreground" : "text-muted-foreground/60"
                            )}
                          >
                            {step.microCopy}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Outputs strip */}
              <div className="mt-6 pt-6 border-t border-border">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Outputs</p>
                <div className="flex flex-wrap gap-2 min-h-[2rem]">
                  {(pipelineSteps.find(s => s.id === activeStep)?.outputs || pipelineSteps[5].outputs).map((output, idx) => (
                    <span
                      key={output}
                      className={cn(
                        "text-xs font-medium px-3 h-6 inline-flex items-center rounded-full border transition-all duration-300",
                        idx % 4 === 0 && "bg-primary/10 border-primary/30 text-primary",
                        idx % 4 === 1 && "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400",
                        idx % 4 === 2 && "bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400",
                        idx % 4 === 3 && "bg-chart-2/10 border-chart-2/30 text-chart-2"
                      )}
                    >
                      {output}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </AnimatedSection>
        </div>
      </div>
    </section>
  );
}
