import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { AnimatedSection } from "@/components/AnimatedSection";

const Privacy = () => {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container mx-auto px-4 lg:px-8 py-24 lg:py-32">
        <AnimatedSection animation="fade-up">
          <div className="max-w-3xl mx-auto">
            <h1 className="text-4xl font-display font-bold text-foreground mb-4">
              Privacy Policy
            </h1>
            <p className="text-muted-foreground mb-12">
              Last updated: {new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
            </p>

            <div className="prose prose-neutral dark:prose-invert max-w-none space-y-8">
              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  1. Introduction
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  QuantGambit Labs, LLC ("QuantGambit," "we," "us," or "our") is committed to protecting your privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our quantitative trading infrastructure platform.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  2. Information We Collect
                </h2>
                <h3 className="text-lg font-semibold text-foreground mt-6 mb-3">Account Information</h3>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  When you register for an account, we collect your name, email address, company name, and other contact information necessary to provide our services.
                </p>
                <h3 className="text-lg font-semibold text-foreground mt-6 mb-3">Exchange API Credentials</h3>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  To facilitate trading operations, you may provide API keys for supported exchanges. These credentials are encrypted at rest and in transit using industry-standard encryption protocols. We strongly recommend providing keys with trading-only permissions—no withdrawal access.
                </p>
                <h3 className="text-lg font-semibold text-foreground mt-6 mb-3">Trading & Operational Data</h3>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  We collect trading activity data, decision traces, configuration changes, and system events to provide observability, analytics, and compliance features.
                </p>
                <h3 className="text-lg font-semibold text-foreground mt-6 mb-3">Usage Information</h3>
                <p className="text-muted-foreground leading-relaxed">
                  We automatically collect information about your interaction with our platform, including IP addresses, browser type, device information, and access times.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  3. How We Use Your Information
                </h2>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>Provide, maintain, and improve our trading infrastructure services</li>
                  <li>Execute trading operations on your behalf via connected exchanges</li>
                  <li>Generate analytics, decision traces, and compliance reports</li>
                  <li>Send administrative notifications and service updates</li>
                  <li>Respond to inquiries and provide customer support</li>
                  <li>Detect and prevent fraud, abuse, or security incidents</li>
                  <li>Comply with legal obligations and regulatory requirements</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  4. Data Security
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  We implement robust security measures including encryption at rest and in transit, multi-factor authentication requirements for live trading, environment separation (dev/paper/live), and comprehensive audit logging. However, no method of transmission over the Internet is 100% secure, and we cannot guarantee absolute security.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  5. Data Retention
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  We retain your personal information for as long as your account is active or as needed to provide services. Trading data, decision traces, and audit logs are retained according to regulatory requirements and your subscription terms. You may request deletion of your data subject to legal retention requirements.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  6. Information Sharing
                </h2>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  We do not sell your personal information. We may share information with:
                </p>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>Service providers who assist in operating our platform</li>
                  <li>Connected exchanges as necessary for trading operations</li>
                  <li>Legal authorities when required by law or to protect our rights</li>
                  <li>Affiliated entities in connection with corporate transactions</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  7. Your Rights
                </h2>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  Depending on your jurisdiction, you may have rights to:
                </p>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>Access and receive a copy of your personal data</li>
                  <li>Correct inaccurate or incomplete information</li>
                  <li>Request deletion of your personal data</li>
                  <li>Object to or restrict certain processing activities</li>
                  <li>Data portability</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  8. Contact Us
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  If you have questions about this Privacy Policy or wish to exercise your rights, please contact us at{" "}
                  <a href="mailto:privacy@quantgambit.com" className="text-primary hover:underline">
                    privacy@quantgambit.com
                  </a>
                </p>
              </section>
            </div>
          </div>
        </AnimatedSection>
      </main>
      <Footer />
    </div>
  );
};

export default Privacy;
