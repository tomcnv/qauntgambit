// Landing page content data

// ─────────────────────────────────────────────────────────────────────────────
// Navigation
// ─────────────────────────────────────────────────────────────────────────────

export const navItems = [
  { label: "How It Works", href: "#how-it-works" },
  { label: "Workbenches", href: "#workbenches" },
  { label: "Security", href: "#security" },
  { label: "Technical Overview", href: "/technical-overview" },
];

// ─────────────────────────────────────────────────────────────────────────────
// Hero
// ─────────────────────────────────────────────────────────────────────────────

export const heroProofChips = [
  "Multi-exchange: Binance · Bybit · OKX",
  "25+ adaptive strategies",
  "Sub-100ms execution",
  "Full decision audit trail",
];

// ─────────────────────────────────────────────────────────────────────────────
// Core Pillars
// ─────────────────────────────────────────────────────────────────────────────

export const corePillars = [
  {
    id: "governance",
    title: "Governance & Versioning",
    features: [
      "Versioned trading profiles with Git-style diffing",
      "Staged rollouts from paper → testnet → live",
      "Immutable config snapshots for every trade",
    ],
    outcome: "Every decision traceable to a specific config revision",
  },
  {
    id: "observability",
    title: "Deep Observability",
    features: [
      "Full decision trace: signals → routing → execution",
      "Real-time latency histograms and queue depth",
      "Per-symbol, per-strategy granular metrics",
    ],
    outcome: "No black boxes — see exactly why trades happened",
  },
  {
    id: "safety",
    title: "Layered Risk Controls",
    features: [
      "Position, symbol, and account-level limits",
      "Automatic position guardians with kill switches",
      "Cooldown circuits and drawdown breakers",
    ],
    outcome: "Multiple layers of protection, always on",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// How It Works
// ─────────────────────────────────────────────────────────────────────────────

export const howItWorksSteps = [
  {
    number: "01",
    title: "Connect Exchange",
    description:
      "Securely link your exchange accounts. API keys are encrypted at rest and never leave your control.",
    input: "Exchange API credentials (read/trade permissions)",
    output: "Verified connection with balance sync",
  },
  {
    number: "02",
    title: "Configure Profile",
    description:
      "Select from 25+ battle-tested strategy profiles or create your own. Each profile version is tracked and auditable.",
    input: "Risk tolerance, symbols, position sizing rules",
    output: "Versioned trading profile ready for deployment",
  },
  {
    number: "03",
    title: "Paper Test",
    description:
      "Run your profile against live market data without risking capital. Validate signals and execution logic.",
    input: "Live market data stream",
    output: "Simulated PnL and decision trace logs",
  },
  {
    number: "04",
    title: "Go Live",
    description:
      "Promote your validated profile to live trading. Start on testnet, then scale to production when confident.",
    input: "Paper-validated profile",
    output: "Live orders with full audit trail",
  },
  {
    number: "05",
    title: "Monitor & Replay",
    description:
      "Watch positions in real-time. When something unexpected happens, replay the exact market conditions and decision path.",
    input: "Incident timestamp or trade ID",
    output: "Complete reconstruction of what happened and why",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Workbenches
// ─────────────────────────────────────────────────────────────────────────────

export const workbenchTabs = [
  {
    id: "trading-ops",
    title: "Trading Ops",
    description:
      "Central command for managing all active bots, positions, and daily operations.",
    persona: "Day-to-day operators and traders",
    bullets: [
      "Real-time position dashboard with PnL attribution",
      "One-click emergency controls (pause, close all, kill switch)",
      "Queue health and execution latency monitoring",
      "Active alerts and anomaly notifications",
    ],
    keyMetric: "Current Exposure",
    secondaryMetric: "Realized PnL",
  },
  {
    id: "signals",
    title: "Signals",
    description:
      "Deep dive into what your strategies are seeing and why they're making decisions.",
    persona: "Strategy developers and analysts",
    bullets: [
      "Live signal stream with classification breakdowns",
      "Per-symbol market regime analysis",
      "Strategy routing decisions with confidence scores",
      "Historical signal accuracy metrics",
    ],
    keyMetric: "Signal Hit Rate",
    secondaryMetric: "Avg Decision Time",
  },
  {
    id: "allocator",
    title: "Capital Allocator",
    description:
      "Control how capital flows between strategies, symbols, and risk buckets.",
    persona: "Portfolio managers and risk allocators",
    bullets: [
      "Visual capital allocation across bots and strategies",
      "Dynamic rebalancing rules and thresholds",
      "Per-credential trading capital limits",
      "Utilization vs. approved capital tracking",
    ],
    keyMetric: "Capital Utilization",
    secondaryMetric: "Available Reserve",
  },
  {
    id: "risk",
    title: "Risk Dashboard",
    description:
      "Comprehensive view of exposure, limits, and circuit breaker states.",
    persona: "Risk managers and compliance",
    bullets: [
      "Multi-layer limit monitoring (position → symbol → account)",
      "Drawdown circuit breaker status",
      "Cooldown timers and recent trigger events",
      "Concentration risk by symbol and sector",
    ],
    keyMetric: "Max Drawdown",
    secondaryMetric: "Active Limits Hit",
  },
  {
    id: "replay",
    title: "Incident Replay",
    description:
      "Time-travel debugging for understanding exactly what happened during any trade or incident.",
    persona: "Forensic analysis and post-mortems",
    bullets: [
      "Reconstruct market state at any timestamp",
      "Step through decision pipeline frame by frame",
      "Compare expected vs actual execution",
      "Export detailed audit reports",
    ],
    keyMetric: "Events Captured",
    secondaryMetric: "Replay Latency",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Security
// ─────────────────────────────────────────────────────────────────────────────

export const securitySubsections = [
  {
    title: "Encrypted Secrets Storage",
    description:
      "API keys encrypted at rest using AES-256. Decrypted only in memory during execution.",
  },
  {
    title: "Zero Trust Architecture",
    description:
      "Every service authenticates every request. No implicit trust between components.",
  },
  {
    title: "Multi-Factor Authentication",
    description:
      "Required for all dashboard access. TOTP-based with backup codes.",
  },
  {
    title: "Immutable Audit Logs",
    description:
      "Every config change, every trade, every decision logged to append-only storage.",
  },
  {
    title: "Emergency Kill Switches",
    description:
      "Hardware-level kill switches and automatic position guardians for rapid response.",
  },
];

export const faqs = [
  {
    question: "Who is QuantGambit for?",
    answer:
      "QuantGambit is built for systematic traders, prop desks, and trading teams who need institutional-grade infrastructure for crypto futures. If you're running more than a hobby bot and care about traceability, versioning, and operational discipline — we're built for you.",
  },
  {
    question: "What exchanges do you support?",
    answer:
      "We currently support Binance, Bybit, and OKX for perpetual futures. All exchanges work in testnet and production modes. Additional exchanges are on our roadmap.",
  },
  {
    question: "Is my exchange API key safe?",
    answer:
      "Yes. API keys are encrypted at rest using AES-256 and only decrypted in isolated runtime memory. We never store keys in plaintext, and they never leave your infrastructure if self-hosted.",
  },
  {
    question: "Can I run this on my own servers?",
    answer:
      "Yes. QuantGambit is designed for self-hosted deployment. We provide Docker images and Terraform modules for AWS/GCP. Managed cloud hosting is also available.",
  },
  {
    question: "What's the difference between paper and live trading?",
    answer:
      "Paper trading runs the exact same pipeline as live — same signals, same routing, same execution logic — but orders are simulated. This ensures what you test is what you deploy.",
  },
  {
    question: "How do profiles and strategies work?",
    answer:
      "Profiles are versioned configurations that define how a bot trades: which strategies are active, risk limits, position sizing rules, and more. Each profile change is tracked, so you can always trace a trade back to its exact config.",
  },
  {
    question: "What happens if something goes wrong?",
    answer:
      "Multiple safety layers: per-position stops, symbol-level limits, account drawdown breakers, and automatic position guardians. Plus, every decision is logged for replay and forensic analysis.",
  },
  {
    question: "How do I get access?",
    answer:
      "We're in private beta. Request access and we'll reach out to discuss your use case and get you onboarded.",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Comparison
// ─────────────────────────────────────────────────────────────────────────────

export const comparisonCompetitors = [
  { id: "quantgambit", name: "QuantGambit", highlight: true },
  { id: "genericBot", name: "Generic Bot" },
  { id: "exchangeBot", name: "Exchange Bot" },
  { id: "copyTrade", name: "Copy Trade" },
];

export const comparisonRows = [
  {
    feature: "Multi-exchange support",
    quantgambit: true,
    genericBot: "partial",
    exchangeBot: false,
    copyTrade: "partial",
  },
  {
    feature: "Versioned strategy configs",
    quantgambit: true,
    genericBot: false,
    exchangeBot: false,
    copyTrade: false,
  },
  {
    feature: "Full decision audit trail",
    quantgambit: true,
    genericBot: false,
    exchangeBot: false,
    copyTrade: false,
  },
  {
    feature: "Incident replay & forensics",
    quantgambit: true,
    genericBot: false,
    exchangeBot: false,
    copyTrade: false,
  },
  {
    feature: "Paper → testnet → live pipeline",
    quantgambit: true,
    genericBot: "partial",
    exchangeBot: "partial",
    copyTrade: false,
  },
  {
    feature: "Multi-layer risk controls",
    quantgambit: true,
    genericBot: "partial",
    exchangeBot: "partial",
    copyTrade: false,
  },
  {
    feature: "Position guardians with kill switch",
    quantgambit: true,
    genericBot: false,
    exchangeBot: false,
    copyTrade: false,
  },
  {
    feature: "Self-hosted option",
    quantgambit: true,
    genericBot: "partial",
    exchangeBot: false,
    copyTrade: false,
  },
  {
    feature: "API key encryption at rest",
    quantgambit: true,
    genericBot: "partial",
    exchangeBot: true,
    copyTrade: "partial",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Footer
// ─────────────────────────────────────────────────────────────────────────────

export const footerLinks: Record<string, { label: string; href: string }[]> = {
  Product: [
    { label: "Features", href: "#features" },
    { label: "Workbenches", href: "#workbenches" },
    { label: "Security", href: "#security" },
    { label: "Documentation", href: "#" },
  ],
  Company: [
    { label: "About", href: "#" },
    { label: "Blog", href: "#" },
    { label: "Careers", href: "#" },
    { label: "Contact", href: "#" },
  ],
  Legal: [
    { label: "Privacy Policy", href: "/privacy" },
    { label: "Terms of Service", href: "/terms" },
    { label: "Security Controls", href: "/security-controls" },
  ],
};
