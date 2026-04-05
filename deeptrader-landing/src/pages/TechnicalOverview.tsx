import { Link } from "react-router-dom";
import { ArrowLeft, Shield, Layers, Activity, Users, Lock, GitBranch, BarChart3, Globe, Key, Target, ChevronRight } from "lucide-react";
import { AnimatedSection } from "@/components/AnimatedSection";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

const sections = [
  {
    id: "problem",
    title: "1. Problem Framing: Execution + Ops is the Product",
    icon: Target,
    content: (
      <div className="space-y-4">
        <p>Many "quant platforms" excel at research, but live systematic trading typically fails in production seams:</p>
        <ul className="space-y-3 list-none">
          <li className="flex gap-3">
            <span className="text-primary font-semibold">Execution reality:</span>
            <span>Partial fills, venue constraints, microstructure drift, rate limits, timeouts, and cost drag.</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold">Operational drift:</span>
            <span>Configuration changes without diffs/approvals, unclear "trade vs no-trade" explanations, weak rollback stories.</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold">Risk plumbing:</span>
            <span>Limits that exist as dashboards, not runtime gates; bot contention when scaling concurrency.</span>
          </li>
        </ul>
        <p className="text-foreground font-medium mt-4">QuantGambit is built so decisions are explainable, controls are enforceable, and incidents are reproducible.</p>
      </div>
    ),
  },
  {
    id: "architecture",
    title: "2. Architecture: Hot Path vs Cold Path",
    icon: Layers,
    content: (
      <div className="space-y-6">
        <p>QuantGambit is organized as two cooperating planes:</p>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Hot Path (Latency-Critical Runtime)</h4>
          <p className="text-sm text-muted-foreground mb-3">Goal: Produce deterministic decisions and execution intents under strict safety constraints.</p>
          <ul className="space-y-2 text-sm">
            <li>• Stage-based pipeline with explicit gates (readiness → context → signal → risk → sizing → execution)</li>
            <li>• Event-driven triggering (react to market updates rather than polling loops)</li>
            <li>• Non-blocking design: the decision loop does not depend on heavy storage/analytics</li>
          </ul>
        </div>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Cold Path (Control Plane, Governance, Forensics)</h4>
          <p className="text-sm text-muted-foreground mb-3">Goal: Make production behavior operable, inspectable, and auditable.</p>
          <ul className="space-y-2 text-sm">
            <li>• Decision trace storage for explainability and auditability</li>
            <li>• State snapshots captured at key moments for reconstruction</li>
            <li>• Incident replay to answer "what happened and why" quickly</li>
            <li>• Governance workflows: versioning, diffs, promotions, approvals, and exports</li>
          </ul>
        </div>
      </div>
    ),
  },
  {
    id: "events",
    title: "3. Event-Driven Core: Traces, Snapshots, and Replay",
    icon: Activity,
    content: (
      <div className="space-y-6">
        <p>QuantGambit models trading as a stream of events: <code className="bg-muted px-2 py-1 rounded text-sm">market → decision → order → fill → position/PnL</code></p>
        
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold text-foreground mb-2">Decision Traces (Explainability)</h4>
            <p className="text-sm text-muted-foreground mb-2">Every decision produces a structured trace capturing:</p>
            <ul className="text-sm space-y-1">
              <li>• Stage outcomes (pass/fail)</li>
              <li>• Rejection reasons (if any)</li>
              <li>• Timing/latency attributes</li>
              <li>• Final execution intent and outcome</li>
            </ul>
            <p className="text-sm text-foreground mt-2">This makes "why didn't it trade?" answerable with evidence instead of interpretation.</p>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Snapshots (Reproducibility)</h4>
            <p className="text-sm text-muted-foreground mb-2">Snapshots store enough context to reconstruct behavior without blocking the hot path:</p>
            <ul className="text-sm space-y-1">
              <li>• Market context inputs</li>
              <li>• Decision context</li>
              <li>• Account/position/PnL state (at relevant boundaries)</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Incident Replay (Forensics)</h4>
            <p className="text-sm text-muted-foreground mb-2">Replay reconstructs a timeline for a symbol/time window by assembling:</p>
            <ul className="text-sm space-y-1">
              <li>• Snapshots</li>
              <li>• Traces</li>
              <li>• Trade + position lifecycle events</li>
            </ul>
            <p className="text-sm text-foreground mt-2">This supports post-mortems, debugging, and exportable incident bundles for offline review.</p>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "modes",
    title: "4. Operating Modes: Solo vs Team vs Prop",
    icon: Users,
    content: (
      <div className="space-y-4">
        <p>QuantGambit supports different operating constraints without changing strategy logic.</p>
        
        <div className="grid gap-4">
          <div className="bg-card border border-border rounded-lg p-5">
            <h4 className="font-semibold text-foreground mb-2">Solo</h4>
            <ul className="text-sm space-y-1">
              <li>• Single active bot per trading account scope</li>
              <li>• Simplified ops surface area while retaining the same telemetry and controls</li>
            </ul>
          </div>
          
          <div className="bg-card border border-border rounded-lg p-5">
            <h4 className="font-semibold text-foreground mb-2">Team</h4>
            <ul className="text-sm space-y-1">
              <li>• Multiple concurrent bots</li>
              <li>• Conflict prevention via symbol ownership locks to prevent two bots from trading the same symbol simultaneously</li>
            </ul>
          </div>
          
          <div className="bg-card border border-border rounded-lg p-5">
            <h4 className="font-semibold text-foreground mb-2">Prop</h4>
            <ul className="text-sm space-y-1">
              <li>• Many concurrent bots across symbols and sleeves</li>
              <li>• Symbol locks</li>
              <li>• Per-bot budgets within a shared risk pool</li>
              <li>• Explicit, machine-parseable rejection reason codes suitable for desk workflows</li>
            </ul>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "risk",
    title: "5. Risk Model: Risk Pool → Budgets → Enforcement Gate",
    icon: Shield,
    content: (
      <div className="space-y-6">
        <p className="text-foreground font-medium">QuantGambit's philosophy: make unsafe actions unrepresentable.</p>
        
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold text-foreground mb-2">Risk Pool Boundary (Account-Scoped)</h4>
            <p className="text-sm text-muted-foreground">Trading accounts define the shared boundary for balances/margin, account-wide limits, and emergency controls (kill switches).</p>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Policies (Hard Caps)</h4>
            <ul className="text-sm space-y-1">
              <li>• Max daily loss / drawdown controls</li>
              <li>• Leverage and position caps</li>
              <li>• Circuit breaker behavior</li>
              <li>• Live-trading enablement gates</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Bot Budgets (Allocations)</h4>
            <p className="text-sm text-muted-foreground mb-2">Budgets allocate risk within a pool, enabling concurrency without losing control:</p>
            <ul className="text-sm space-y-1">
              <li>• Max daily loss per bot</li>
              <li>• Max open positions</li>
              <li>• Leverage caps</li>
              <li>• Order-rate limits (optional)</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Single Enforcement Gate (One Source of Truth)</h4>
            <p className="text-sm text-muted-foreground">Every execution intent passes through an ordered validation gate that can allow, clamp/throttle, or reject. Rejections return structured reason codes, enabling a clear rejection funnel and reliable auditability.</p>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "governance",
    title: "6. Governance: Versioning, Diffs, Promotions, Approvals",
    icon: GitBranch,
    content: (
      <div className="space-y-6">
        <p className="text-foreground font-medium">QuantGambit treats configuration like a deployment artifact.</p>
        
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold text-foreground mb-2">Versioned Configurations</h4>
            <ul className="text-sm space-y-1">
              <li>• Immutable history for key configurations</li>
              <li>• Before/after capture with audit records</li>
              <li>• Rollback-ready by design</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Promotion Workflow (Research → Paper → Live)</h4>
            <ul className="text-sm space-y-1">
              <li>• Promotion requests across environments</li>
              <li>• Optional approvals (including "four-eyes" constraints)</li>
              <li>• Config diffs highlighting risk/symbol/profile/feature changes</li>
              <li>• Complete promotion history</li>
            </ul>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "observability",
    title: "7. Observability: Decision Accountability + Execution Analytics",
    icon: BarChart3,
    content: (
      <div className="space-y-6">
        <p className="text-foreground font-medium">QuantGambit is built for explainable execution.</p>
        
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold text-foreground mb-2">Decision Accountability</h4>
            <ul className="text-sm space-y-1">
              <li>• Stage-by-stage traces</li>
              <li>• Searchable decision and reject history</li>
              <li>• Audit logging + exports</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-foreground mb-2">Execution Analytics (TCA + Capacity)</h4>
            <p className="text-sm text-muted-foreground mb-2">QuantGambit supports TCA to quantify:</p>
            <ul className="text-sm space-y-1">
              <li>• Slippage vs decision-time reference prices</li>
              <li>• Fees and aggregated cost drag</li>
              <li>• Capacity curves by notional bucket (how costs scale with size)</li>
            </ul>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "venues",
    title: "8. Venue Model and Integrations",
    icon: Globe,
    content: (
      <div className="space-y-4">
        <p>QuantGambit supports multiple venues and can run in:</p>
        <ul className="text-sm space-y-2">
          <li>• <span className="font-medium text-foreground">Paper mode:</span> Simulation / controlled experimentation</li>
          <li>• <span className="font-medium text-foreground">Live mode:</span> Real connectivity</li>
        </ul>
        <p className="text-foreground font-medium mt-4">Credential handling follows the principle: API keys should not permit withdrawals.</p>
      </div>
    ),
  },
  {
    id: "security",
    title: "9. Security Posture",
    icon: Key,
    content: (
      <div className="space-y-4">
        <p>QuantGambit is designed with:</p>
        <ul className="text-sm space-y-2">
          <li>• Encrypted secrets storage</li>
          <li>• Least-privilege credential guidance</li>
          <li>• Environment separation and live-trading gates</li>
          <li>• Audit logging, retention, and export support</li>
          <li>• Incident replay for forensic reconstruction</li>
        </ul>
        <Link to="/security-controls" className="inline-flex items-center gap-2 text-primary hover:underline mt-4 text-sm font-medium">
          See Security & Controls Brief <ChevronRight className="h-4 w-4" />
        </Link>
      </div>
    ),
  },
  {
    id: "roadmap",
    title: "10. Roadmap (Subject to Change)",
    icon: Target,
    content: (
      <div className="space-y-4">
        <p>Near-term areas:</p>
        <ul className="text-sm space-y-2">
          <li>• Parameter sweeps / walk-forward workflows and UI</li>
          <li>• Allocator enhancements and capital deployment controls</li>
          <li>• Deeper execution attribution (latency + slippage)</li>
          <li>• Expanded governance controls and approval policies</li>
        </ul>
      </div>
    ),
  },
];

const differentiators = [
  "Enforceable operating modes for concurrency (Solo/Team/Prop)",
  "Risk pool + budgets + a single enforcement gate with reason codes",
  "Reproducibility via traces, snapshots, and incident replay",
  "Governance via versioning, diffs, promotions, and approvals",
  "Execution-grade analytics (TCA and capacity)",
];

export default function TechnicalOverview() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 lg:px-8 py-4">
          <Link to="/" className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="h-4 w-4" />
            Back to Home
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="py-16 lg:py-24 border-b border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <AnimatedSection animation="fade-up">
            <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">Technical Overview</p>
            <h1 className="text-4xl lg:text-5xl xl:text-6xl font-display font-bold text-foreground mb-6">
              QuantGambit Technical Overview
            </h1>
            <p className="text-lg text-muted-foreground max-w-3xl mb-8">
              For quant teams, engineering leads, and trading operations. This document explains QuantGambit's execution architecture, operating modes, enforceable controls, and observability model.
            </p>
          </AnimatedSection>
        </div>
      </section>

      {/* Executive Summary */}
      <section className="py-16 border-b border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <AnimatedSection animation="fade-up">
            <div className="bg-card border border-border rounded-2xl p-8 lg:p-10">
              <h2 className="text-2xl font-display font-semibold text-foreground mb-6">Executive Summary</h2>
              <p className="text-muted-foreground mb-6 leading-relaxed">
                QuantGambit is an execution control plane for systematic crypto trading. It's designed to answer three questions with evidence:
              </p>
              <ul className="space-y-3 mb-6">
                <li className="flex gap-3">
                  <span className="text-primary font-semibold">What happened?</span>
                  <span className="text-muted-foreground">(orders, fills, positions, PnL)</span>
                </li>
                <li className="flex gap-3">
                  <span className="text-primary font-semibold">Why did it happen?</span>
                  <span className="text-muted-foreground">(decision traces + rejection reasons)</span>
                </li>
                <li className="flex gap-3">
                  <span className="text-primary font-semibold">Can we reproduce it?</span>
                  <span className="text-muted-foreground">(snapshots + incident replay)</span>
                </li>
              </ul>
              <p className="text-foreground font-medium">
                Unlike research-first platforms, QuantGambit treats production trading as an operational discipline: enforceable risk, governed configuration, and forensic replay are first-class products.
              </p>
            </div>
          </AnimatedSection>
        </div>
      </section>

      {/* Main Content */}
      <section className="py-16">
        <div className="container mx-auto px-4 lg:px-8">
          <div className="max-w-4xl">
            <Accordion type="single" collapsible className="w-full space-y-4">
              {sections.map((section, idx) => {
                const Icon = section.icon;
                return (
                  <AnimatedSection key={section.id} animation="fade-up" delay={idx * 50}>
                    <AccordionItem value={section.id} className="border border-border rounded-xl px-6 bg-card/50">
                      <AccordionTrigger className="text-left font-semibold hover:text-primary transition-colors py-5">
                        <div className="flex items-center gap-4">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 border border-primary/20">
                            <Icon className="h-5 w-5 text-primary" />
                          </div>
                          <span>{section.title}</span>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent className="text-muted-foreground pb-6 pt-2">
                        {section.content}
                      </AccordionContent>
                    </AccordionItem>
                  </AnimatedSection>
                );
              })}
            </Accordion>
          </div>
        </div>
      </section>

      {/* Why Different */}
      <section className="py-16 bg-muted/30 border-t border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <AnimatedSection animation="fade-up">
            <div className="max-w-4xl">
              <h2 className="text-2xl lg:text-3xl font-display font-bold text-foreground mb-6">
                Why QuantGambit is Different
              </h2>
              <p className="text-muted-foreground mb-8">
                QuantGambit differentiates by treating live execution as an operational discipline:
              </p>
              <ul className="space-y-4">
                {differentiators.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-3">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
                      <div className="h-2 w-2 rounded-full bg-primary" />
                    </div>
                    <span className="text-foreground">{item}</span>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground mt-8 italic">
                This document intentionally avoids performance claims and sensitive implementation details. It focuses on system behavior and controls customers can validate.
              </p>
            </div>
          </AnimatedSection>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 border-t border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <AnimatedSection animation="fade-up">
            <div className="flex flex-col sm:flex-row gap-4 items-start">
              <Button asChild size="lg">
                <Link to="/security-controls">
                  <Lock className="h-4 w-4 mr-2" />
                  Security & Controls Brief
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link to="/request-access">
                  Request Access
                </Link>
              </Button>
            </div>
          </AnimatedSection>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 border-t border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <p className="text-sm text-muted-foreground">
            © {new Date().getFullYear()} QuantGambit. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
