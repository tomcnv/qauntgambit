import { Link } from "react-router-dom";
import { ArrowLeft, Shield, Key, Lock, Users, Activity, Database, FileText, AlertTriangle, CheckCircle2, XCircle, Settings } from "lucide-react";
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
    id: "threat",
    title: "1. Threat Model",
    icon: AlertTriangle,
    content: (
      <div className="space-y-4">
        <p>QuantGambit's controls are built around common operational and security risks in live trading systems:</p>
        <ul className="space-y-3">
          <li className="flex gap-3">
            <span className="text-primary font-semibold shrink-0">Credential compromise:</span>
            <span>Secret leakage via logs, UI surfaces, exports, or workstation mishandling</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold shrink-0">Over-privileged keys:</span>
            <span>Keys able to withdraw funds or perform high-risk administrative actions</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold shrink-0">Operator error:</span>
            <span>Wrong environment, wrong account, wrong bot/config activated</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold shrink-0">Runaway execution:</span>
            <span>Continued trading under degraded market data, venue instability, or model failure</span>
          </li>
          <li className="flex gap-3">
            <span className="text-primary font-semibold shrink-0">Insufficient forensics:</span>
            <span>Inability to reconstruct what the system knew and why it acted</span>
          </li>
        </ul>
        <p className="text-sm text-muted-foreground mt-4 italic">
          Out of scope: physical attacks, customer-side endpoint compromise, and exchange-side security events beyond our control.
        </p>
      </div>
    ),
  },
  {
    id: "credentials",
    title: "2. Credential Handling Model",
    icon: Key,
    content: (
      <div className="space-y-6">
        <div>
          <h4 className="font-semibold text-foreground mb-2">2.1 Secret Storage and Access Boundaries</h4>
          <ul className="text-sm space-y-1">
            <li>• Secrets are encrypted at rest</li>
            <li>• Secrets are never returned in API responses</li>
            <li>• UI surfaces display masked identifiers only (no raw keys)</li>
          </ul>
        </div>
        
        <div>
          <h4 className="font-semibold text-foreground mb-2">2.2 Namespacing and Scoping</h4>
          <p className="text-sm text-muted-foreground mb-2">Credentials are scoped by:</p>
          <ul className="text-sm space-y-1">
            <li>• Tenant</li>
            <li>• Exchange account</li>
            <li>• Environment (dev / paper / live)</li>
            <li>• Credential identifier (rotation-friendly)</li>
          </ul>
        </div>
        
        <div>
          <h4 className="font-semibold text-foreground mb-2">2.3 "No Withdrawals" Policy (Safety Constraint)</h4>
          <p className="text-sm text-muted-foreground">
            QuantGambit is designed around a strict constraint: connected credentials must not permit withdrawals. During credential verification, QuantGambit checks for withdrawal capability. If withdrawal permission is detected, credentials are rejected and cannot be activated.
          </p>
        </div>
      </div>
    ),
  },
  {
    id: "permissions",
    title: "3. Exchange Permission Guidance",
    icon: Lock,
    content: (
      <div className="space-y-4">
        <p className="font-medium text-foreground">Recommended permissions:</p>
        <div className="bg-card border border-border rounded-lg p-5 space-y-3">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-500" />
            <span className="text-sm"><span className="font-medium">Read:</span> balances, positions, orders</span>
          </div>
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-500" />
            <span className="text-sm"><span className="font-medium">Trade:</span> create/amend/cancel orders</span>
          </div>
          <div className="flex items-center gap-3">
            <XCircle className="h-5 w-5 text-destructive" />
            <span className="text-sm"><span className="font-medium">Disallow:</span> withdrawals and funds-movement permissions</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "environment",
    title: "4. Environment Separation and Live-Trading Gates",
    icon: Settings,
    content: (
      <div className="space-y-4">
        <p className="font-medium text-foreground">Environment is a first-class boundary:</p>
        <ul className="text-sm space-y-2">
          <li>• Credentials are environment-scoped</li>
          <li>• Policies can explicitly gate live trading</li>
          <li>• Lifecycle operations enforce that live trading cannot run unless explicitly enabled</li>
        </ul>
        <p className="text-foreground font-medium mt-4">
          This ensures "Live" is policy-controlled rather than merely a UI toggle.
        </p>
      </div>
    ),
  },
  {
    id: "controls",
    title: "5. Operational Controls",
    icon: Shield,
    content: (
      <div className="space-y-6">
        <div>
          <h4 className="font-semibold text-foreground mb-2">5.1 Kill Switch (Account-Scoped)</h4>
          <p className="text-sm text-muted-foreground">QuantGambit supports emergency controls to block new trading activity and stop running bots under an exchange account scope.</p>
        </div>
        
        <div>
          <h4 className="font-semibold text-foreground mb-2">5.2 Circuit Breaker (Loss Threshold + Cooldown)</h4>
          <p className="text-sm text-muted-foreground">Policies can automatically stop or block trading under predefined conditions (e.g., loss limits, abnormal rejection rates, data degradation).</p>
        </div>
        
        <div>
          <h4 className="font-semibold text-foreground mb-2">5.3 Mode-Aware Concurrency Controls</h4>
          <ul className="text-sm space-y-1">
            <li>• <span className="font-medium">Solo:</span> Single active bot per exchange account scope</li>
            <li>• <span className="font-medium">Team/Prop:</span> Symbol ownership locks prevent bot conflicts</li>
            <li>• <span className="font-medium">Prop:</span> Per-bot budgets can be required and enforced</li>
          </ul>
        </div>
        
        <div>
          <h4 className="font-semibold text-foreground mb-2">5.4 Single Enforcement Gate</h4>
          <p className="text-sm text-muted-foreground mb-2">Every execution intent passes through a single ordered gate evaluating:</p>
          <ul className="text-sm space-y-1">
            <li>• Tenant governance and live enablement</li>
            <li>• Exchange account policy limits and kill/circuit-breaker state</li>
            <li>• Bot budgets</li>
            <li>• Symbol ownership locks</li>
            <li>• Venue constraints (min notional, leverage rules, etc.)</li>
          </ul>
          <p className="text-sm text-foreground mt-2">Rejections return structured reason codes suitable for ops workflows and analytics.</p>
        </div>
      </div>
    ),
  },
  {
    id: "audit",
    title: "6. Audit Logging, Retention, and Exports",
    icon: FileText,
    content: (
      <div className="space-y-4">
        <p>QuantGambit supports auditability across:</p>
        <ul className="text-sm space-y-2">
          <li>• Credential lifecycle events (metadata only; no secrets)</li>
          <li>• Bot lifecycle actions (start/stop/pause/resume)</li>
          <li>• Policy changes</li>
          <li>• Promotion/approval actions</li>
          <li>• Enforcement actions (reason codes)</li>
        </ul>
        <p className="text-sm text-muted-foreground mt-4">
          Retention policies can be applied to control-plane logs and traces, and exports enable offline review and incident reporting workflows.
        </p>
      </div>
    ),
  },
  {
    id: "forensics",
    title: "7. Forensics: Traces, Snapshots, Incident Replay",
    icon: Activity,
    content: (
      <div className="space-y-4">
        <p>QuantGambit supports evidence-based investigations via:</p>
        <ul className="text-sm space-y-2">
          <li>• <span className="font-medium">Decision traces:</span> Stage outcomes, rejections, execution results</li>
          <li>• <span className="font-medium">Snapshots:</span> Market/decision context + relevant state boundaries</li>
          <li>• <span className="font-medium">Incident replay:</span> Reconstructs what the system knew and did across a time window</li>
        </ul>
      </div>
    ),
  },
  {
    id: "minimization",
    title: "8. Data Minimization",
    icon: Database,
    content: (
      <div className="space-y-4">
        <p className="font-medium text-foreground">Prevent accidental leakage:</p>
        <ul className="text-sm space-y-2">
          <li>• Secrets excluded from logs and exports</li>
          <li>• Displays show masked identifiers, not raw keys</li>
          <li>• Public surfaces avoid disclosing internal topology</li>
        </ul>
      </div>
    ),
  },
  {
    id: "responsibilities",
    title: "9. Security Responsibilities Split",
    icon: Users,
    content: (
      <div className="space-y-6">
        <p className="text-sm text-muted-foreground">This clarifies "who owns what" in audits and vendor reviews.</p>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Customer Responsibilities</h4>
          <ul className="text-sm space-y-1">
            <li>• Secure operator endpoints (workstations, browsers, password managers)</li>
            <li>• Maintain exchange account security (2FA, IP allowlists if available, exchange-side roles)</li>
            <li>• Create least-privilege API keys (no withdrawals) and rotate on schedule</li>
            <li>• Manage internal access to QuantGambit (who can operate live trading)</li>
          </ul>
        </div>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">QuantGambit Responsibilities</h4>
          <ul className="text-sm space-y-1">
            <li>• Encrypt and protect secrets at rest; never expose secrets via APIs/UI/logs</li>
            <li>• Enforce environment separation and live-trading gates</li>
            <li>• Provide runtime enforcement (limits, kill switches, reason-coded rejections)</li>
            <li>• Provide audit logs, retention controls, and exports</li>
            <li>• Provide forensic replay artifacts (traces/snapshots) for investigations</li>
          </ul>
        </div>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Exchange Responsibilities</h4>
          <ul className="text-sm space-y-1">
            <li>• Enforce API key permission boundaries</li>
            <li>• Maintain venue availability, rate limits, and matching engine integrity</li>
            <li>• Provide exchange-side security features (2FA, key scopes, allowlists)</li>
          </ul>
        </div>
      </div>
    ),
  },
  {
    id: "guarantees",
    title: "10. Control Guarantees vs Configurable Options",
    icon: CheckCircle2,
    content: (
      <div className="space-y-6">
        <p className="text-sm text-muted-foreground">This helps reviewers differentiate "always-on safety" from "policy choice."</p>
        
        <div className="bg-primary/5 border border-primary/20 rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Guaranteed by Design (Non-Optional)</h4>
          <ul className="text-sm space-y-1">
            <li>• Secrets are not returned via API and are masked in UI</li>
            <li>• Credentials are environment-scoped</li>
            <li>• Central enforcement gate evaluates policies before execution</li>
            <li>• Structured reason codes exist for blocks/rejections</li>
            <li>• Decision traces + replay artifacts exist for post-incident analysis</li>
          </ul>
        </div>
        
        <div className="bg-card border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Configurable (Tenant/Admin Policy Choices)</h4>
          <ul className="text-sm space-y-1">
            <li>• Live trading enabled/disabled</li>
            <li>• Loss limits, leverage caps, exposure caps</li>
            <li>• Circuit breaker thresholds and cooldown behavior</li>
            <li>• Retention duration and export cadence</li>
            <li>• Operating mode selection (Solo vs Team vs Prop) and whether bot budgets are mandatory</li>
          </ul>
        </div>
        
        <div className="bg-muted/50 border border-border rounded-lg p-5">
          <h4 className="font-semibold text-foreground mb-3">Exchange-Dependent (Varies by Venue)</h4>
          <ul className="text-sm space-y-1">
            <li>• Whether withdrawal permission is detectable via API</li>
            <li>• Whether IP allowlists are supported</li>
            <li>• Granularity of key scopes and account sub-accounts</li>
          </ul>
        </div>
      </div>
    ),
  },
];

const checklist = [
  "Credential verification rejects keys that permit withdrawals (where venue supports detection)",
  "Live trading cannot start unless enabled at the tenant/account policy layer",
  "Kill switch blocks new orders immediately",
  "Enforcement gate produces machine-readable reason codes",
  "Audit log captures who changed what, when, and from where",
  "Replay reconstructs a trade/incident with decision context and timeline evidence",
];

export default function SecurityControls() {
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
            <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">Security Documentation</p>
            <h1 className="text-4xl lg:text-5xl xl:text-6xl font-display font-bold text-foreground mb-6">
              Security & Controls Brief
            </h1>
            <p className="text-lg text-muted-foreground max-w-3xl mb-4">
              For security reviewers, engineering leads, and prop/ops desks. This document covers credential handling, permission safety, environment separation, auditability, retention, and operational controls.
            </p>
            <p className="text-sm text-muted-foreground italic">
              Non-goals: This document intentionally omits sensitive infrastructure topology and implementation details that would materially aid an attacker.
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
              <p className="text-muted-foreground leading-relaxed">
                QuantGambit is designed to reduce catastrophic failure modes in systematic trading by enforcing least privilege, explicit environment boundaries, runtime safety gates, and forensic traceability. The system assumes credentials and operators can fail; therefore, controls are engineered to prevent unsafe states and produce evidence for post-incident review.
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

      {/* Reviewer Checklist */}
      <section className="py-16 bg-muted/30 border-t border-border">
        <div className="container mx-auto px-4 lg:px-8">
          <AnimatedSection animation="fade-up">
            <div className="max-w-4xl">
              <h2 className="text-2xl lg:text-3xl font-display font-bold text-foreground mb-6">
                Reviewer Checklist
              </h2>
              <p className="text-muted-foreground mb-8">
                What you can verify in a demo:
              </p>
              <ul className="space-y-4">
                {checklist.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-3">
                    <CheckCircle2 className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                    <span className="text-foreground">{item}</span>
                  </li>
                ))}
              </ul>
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
                <Link to="/technical-overview">
                  <FileText className="h-4 w-4 mr-2" />
                  Technical Overview
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
