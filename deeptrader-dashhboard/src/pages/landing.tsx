import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Button } from "../components/ui/button";
import Logo from "../components/logo";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";

const proofPoints = [
  { label: "Live Signals", value: "32 markets" },
  { label: "Avg. latency", value: "210µs" },
  { label: "Daily throughput", value: "3.2M events" },
];

const productHighlights = [
  {
    title: "Hot Path Command",
    description:
      "Latency-first execution and market connectivity tuned for sub-second orchestration.",
  },
  {
    title: "Config Studio",
    description:
      "Multi-tenant governance with promotion workflows, semantic diffing, and audit trails.",
  },
  {
    title: "Allocator Intelligence",
    description:
      "Capacity-aware capital deployment, predictive risk envelopes, and autonomous throttling.",
  },
];

export default function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <div className="absolute inset-0">
        <div className="absolute inset-y-0 left-1/2 w-[40rem] -translate-x-1/2 rounded-full bg-purple-500/10 blur-[150px]" />
        <div className="absolute inset-y-0 right-0 w-[30rem] rounded-full bg-blue-500/10 blur-[200px]" />
      </div>

      <header className="relative z-10 flex items-center justify-between px-10 py-8">
        <Logo />
        <div className="flex items-center gap-3">
          <Link to="/auth/sign-in">
            <Button variant="ghost">Sign in</Button>
          </Link>
          <Link to="/auth/sign-up">
            <Button>Get Started</Button>
          </Link>
        </div>
      </header>

      <main className="relative z-10 px-10 pb-20 pt-6">
        <section className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="space-y-10">
            <Badge variant="outline" className="text-xs uppercase tracking-[0.3em]">
              Built for institutional crypto automation
            </Badge>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              className="text-6xl font-semibold text-white sm:text-7xl"
            >
              Orchestrate every trade path with confidence.
            </motion.h1>
            <p className="max-w-2xl text-xl text-muted-foreground">
              DeepTrader unifies real-time signals, allocator intelligence, and config governance
              into a single control plane so your team can deploy capital with surgical precision.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link to="/auth/sign-up">
                <Button size="lg">Launch Control Center</Button>
              </Link>
              <Link to="/auth/sign-in">
                <Button variant="outline" size="lg">
                  Request a live walkthrough
                </Button>
              </Link>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {proofPoints.map((point) => (
                <div key={point.label} className="rounded-2xl border border-white/5 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">
                    {point.label}
                  </p>
                  <p className="text-2xl font-semibold text-white">{point.value}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="relative">
            <div className="absolute inset-0 rounded-[32px] bg-gradient-to-br from-white/10 to-transparent blur-3xl" />
            <div className="relative rounded-[32px] border border-white/10 bg-black/40 p-8 shadow-elevated backdrop-blur-3xl">
              <p className="text-sm uppercase tracking-[0.3em] text-muted-foreground">
                Mission Control
              </p>
              <h3 className="mt-2 text-2xl font-semibold text-white">State of play</h3>

              <div className="mt-8 grid gap-4">
                {productHighlights.map((item) => (
                  <Card key={item.title} className="border-white/5 bg-white/5">
                    <CardContent className="space-y-2">
                      <p className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
                        {item.title}
                      </p>
                      <p className="text-sm text-muted-foreground">{item.description}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto mt-24 grid max-w-6xl gap-10 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-3xl border border-white/5 bg-white/5 p-8">
            <h4 className="text-xs uppercase tracking-[0.4em] text-muted-foreground">Playbooks</h4>
            <p className="mt-4 text-3xl font-semibold text-white">Hot / Cold Path blueprint</p>
            <p className="mt-4 text-muted-foreground">
              Decouple latency-critical services from analytic workloads. Deploy orchestrators,
              allocators, state publishers, and dashboards independently without losing fidelity.
            </p>
            <ul className="mt-6 space-y-3 text-sm text-muted-foreground">
              <li>• Dedicated command bus for symbol-level throttling</li>
              <li>• Redis-mirrored state snapshots for cold observers</li>
              <li>• WAL streaming with S3 parity for forensic replay</li>
            </ul>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {["Trading Ops", "Signal Lab", "Allocator Studio", "Config Studio"].map((item) => (
              <div key={item} className="rounded-3xl border border-white/5 bg-card/80 p-6">
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">{item}</p>
                <p className="mt-3 text-2xl font-semibold text-white">Coming alive soon</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  Purpose-built workbench to monitor, tune, and deploy {item.toLowerCase()}.
                </p>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

