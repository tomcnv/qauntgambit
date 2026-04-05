import { useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CheckCircle2, Building2, Users, BarChart3, Play, Phone, Eye, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { register, DASHBOARD_URL } from "@/lib/auth";
import { toast } from "sonner";
import quantGambitDark from "@/assets/quantgambit-dark.png";
import quantGambitLight from "@/assets/quantgambit-light.png";

const firmTypes = [
  "Proprietary Trading Firm",
  "Hedge Fund",
  "Family Office",
  "Asset Manager",
  "Market Maker",
  "Other",
];

const aumRanges = [
  "Under $10M",
  "$10M - $50M",
  "$50M - $100M",
  "$100M - $500M",
  "$500M - $1B",
  "Over $1B",
];

type FormType = "access" | "demo" | "sales";

interface FormConfig {
  title: string;
  subtitle: string;
  successTitle: string;
  successMessage: string;
  submitLabel: string;
  icon: React.ReactNode;
  panelTitle: string;
  panelSubtitle: string;
  messagePlaceholder: string;
  messageLabel: string;
}

const formConfigs: Record<FormType, FormConfig> = {
  access: {
    title: "Request access",
    subtitle: "Complete the form below and our team will review your application.",
    successTitle: "Request received",
    successMessage: "Thank you for your interest in QuantGambit. Our team will review your application and reach out within 24-48 hours.",
    submitLabel: "Submit request",
    icon: <ArrowRight className="h-4 w-4" />,
    panelTitle: "Join the next generation of institutional traders",
    panelSubtitle: "QuantGambit is designed for sophisticated trading operations that demand precision, reliability, and scale.",
    messagePlaceholder: "Describe your strategies, current infrastructure, and what you're looking for...",
    messageLabel: "Tell us about your trading operation",
  },
  demo: {
    title: "Request a walkthrough",
    subtitle: "Schedule a personalized demo with our team to see QuantGambit in action.",
    successTitle: "Demo request received",
    successMessage: "Thank you for your interest. Our team will reach out within 24 hours to schedule your personalized walkthrough.",
    submitLabel: "Request demo",
    icon: <Play className="h-4 w-4" />,
    panelTitle: "See QuantGambit in action",
    panelSubtitle: "Get a personalized walkthrough of our execution control plane, decision traces, and incident replay capabilities.",
    messagePlaceholder: "What specific features or workflows would you like to see? Any particular use cases you're interested in?",
    messageLabel: "What would you like to see in the demo?",
  },
  sales: {
    title: "Contact sales",
    subtitle: "Talk to our team about enterprise deployment and pricing.",
    successTitle: "Message received",
    successMessage: "Thank you for reaching out. A member of our sales team will contact you within 24 hours.",
    submitLabel: "Contact sales",
    icon: <Phone className="h-4 w-4" />,
    panelTitle: "Enterprise-ready execution infrastructure",
    panelSubtitle: "Let's discuss how QuantGambit can power your trading operations at scale.",
    messagePlaceholder: "Tell us about your requirements, timeline, and any specific questions you have...",
    messageLabel: "How can we help?",
  },
};

export default function RequestAccess() {
  const [searchParams] = useSearchParams();
  const typeParam = searchParams.get("type") as FormType | null;
  const formType: FormType = typeParam && ["demo", "sales"].includes(typeParam) ? typeParam : "access";
  const config = formConfigs[formType];

  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isDark, setIsDark] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    email: "",
    password: "",
    company: "",
    firmType: "",
    aum: "",
    message: "",
    intent: formType,
  });

  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains("dark"));
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  // Update intent when formType changes
  useEffect(() => {
    setFormData(prev => ({ ...prev, intent: formType }));
  }, [formType]);

  const logo = isDark ? quantGambitDark : quantGambitLight;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      // Generate username from email
      const username = formData.email.split("@")[0];
      
      // Call registration API with enterprise fields in metadata
      await register({
        email: formData.email,
        username,
        password: formData.password,
        firstName: formData.firstName,
        lastName: formData.lastName,
        metadata: {
          company: formData.company,
          firmType: formData.firmType,
          aum: formData.aum,
          message: formData.message,
          intent: formData.intent,
          registrationSource: "landing_page",
          requiresApproval: true,
        },
      });
      
      toast.success("Account created successfully!");
      setIsSubmitted(true);
      
      // Optionally redirect to dashboard after a delay
      // setTimeout(() => {
      //   window.location.href = `${DASHBOARD_URL}/dashboard`;
      // }, 2000);
    } catch (error) {
      toast.error((error as Error).message || "Registration failed");
      setIsLoading(false);
    }
  };

  const handleChange = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  if (isSubmitted) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-8">
        <div className="w-full max-w-md space-y-8 text-center">
          <div className="flex justify-center">
            <Link to="/">
              <img src={logo} alt="QuantGambit" className="h-10 w-auto" />
            </Link>
          </div>

          <div className="space-y-6">
            <div className="mx-auto w-16 h-16 rounded-2xl bg-emerald-500/10 flex items-center justify-center">
              <CheckCircle2 className="h-8 w-8 text-emerald-500" />
            </div>
            <div className="space-y-2">
              <h2 className="text-2xl font-display font-semibold text-foreground">
                {config.successTitle}
              </h2>
              <p className="text-muted-foreground">
                {config.successMessage}
              </p>
            </div>

            <div className="pt-4 space-y-3">
              <Link to="/">
                <Button className="w-full h-11 font-medium shadow-lg shadow-primary/25">
                  Back to homepage
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex">
      {/* Left Panel - Benefits */}
      <div className="hidden lg:flex lg:w-5/12 bg-gradient-to-br from-primary/5 via-background to-primary/10 relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_var(--tw-gradient-stops))] from-primary/10 via-transparent to-transparent" />
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiMyMDIwMjAiIGZpbGwtb3BhY2l0eT0iMC4wMyI+PGNpcmNsZSBjeD0iMzAiIGN5PSIzMCIgcj0iMiIvPjwvZz48L2c+PC9zdmc+')] opacity-50" />

        <div className="relative z-10 flex flex-col justify-between p-12 w-full max-w-2xl ml-auto">
            <Link to="/" className="flex items-center gap-3">
              <img src={logo} alt="QuantGambit" className="h-10 w-auto" />
            </Link>

            <div className="space-y-10">
              <div className="space-y-4">
                <h1 className="text-3xl font-display font-semibold text-foreground leading-tight">
                  {config.panelTitle}
                </h1>
                <p className="text-lg text-muted-foreground">
                  {config.panelSubtitle}
                </p>
              </div>

              <div className="space-y-6">
                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <BarChart3 className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-medium text-foreground">Sub-millisecond execution</h3>
                    <p className="text-sm text-muted-foreground">
                      Ultra-low latency infrastructure optimized for HFT and systematic strategies.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <Building2 className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-medium text-foreground">Enterprise-grade security</h3>
                    <p className="text-sm text-muted-foreground">
                      SOC 2 compliant with multi-sig custody and institutional-grade key management.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <Users className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-medium text-foreground">Dedicated support</h3>
                    <p className="text-sm text-muted-foreground">
                      24/7 priority support with dedicated account managers for enterprise clients.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-6 text-sm text-muted-foreground">
              <span>Trusted by 50+ institutions</span>
              <span>•</span>
              <span>$2B+ monthly volume</span>
            </div>
          </div>
        </div>

      {/* Right Panel - Form */}
      <div className="flex-1 flex items-center justify-center p-8 overflow-y-auto">
        <div className="w-full max-w-md space-y-8 mr-auto">
            {/* Mobile Logo */}
            <div className="lg:hidden flex justify-center mb-8">
              <Link to="/">
                <img src={logo} alt="QuantGambit" className="h-10 w-auto" />
              </Link>
            </div>

            <div className="space-y-2 text-center lg:text-left">
              <h2 className="text-2xl font-display font-semibold text-foreground">
                {config.title}
              </h2>
              <p className="text-muted-foreground">
                {config.subtitle}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Hidden intent field */}
              <input type="hidden" name="intent" value={formData.intent} />

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="firstName" className="text-sm font-medium">
                    First name
                  </Label>
                  <Input
                    id="firstName"
                    placeholder="John"
                    value={formData.firstName}
                    onChange={(e) => handleChange("firstName", e.target.value)}
                    className="h-11 bg-background border-border focus:border-primary focus:ring-primary/20"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="lastName" className="text-sm font-medium">
                    Last name
                  </Label>
                  <Input
                    id="lastName"
                    placeholder="Smith"
                    value={formData.lastName}
                    onChange={(e) => handleChange("lastName", e.target.value)}
                    className="h-11 bg-background border-border focus:border-primary focus:ring-primary/20"
                    required
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="email" className="text-sm font-medium">
                  Work email
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="john@hedgefund.com"
                  value={formData.email}
                  onChange={(e) => handleChange("email", e.target.value)}
                  className="h-11 bg-background border-border focus:border-primary focus:ring-primary/20"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm font-medium">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={formData.password}
                    onChange={(e) => handleChange("password", e.target.value)}
                    className="h-11 pr-10 bg-background border-border focus:border-primary focus:ring-primary/20"
                    required
                    minLength={8}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">Minimum 8 characters</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="company" className="text-sm font-medium">
                  Company
                </Label>
                <Input
                  id="company"
                  placeholder="Your firm name"
                  value={formData.company}
                  onChange={(e) => handleChange("company", e.target.value)}
                  className="h-11 bg-background border-border focus:border-primary focus:ring-primary/20"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="text-sm font-medium">Firm type</Label>
                  <Select
                    value={formData.firmType}
                    onValueChange={(value) => handleChange("firmType", value)}
                  >
                    <SelectTrigger className="h-11 bg-background border-border">
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent>
                      {firmTypes.map((type) => (
                        <SelectItem key={type} value={type}>
                          {type}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-medium">AUM</Label>
                  <Select
                    value={formData.aum}
                    onValueChange={(value) => handleChange("aum", value)}
                  >
                    <SelectTrigger className="h-11 bg-background border-border">
                      <SelectValue placeholder="Select range" />
                    </SelectTrigger>
                    <SelectContent>
                      {aumRanges.map((range) => (
                        <SelectItem key={range} value={range}>
                          {range}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="message" className="text-sm font-medium">
                  {config.messageLabel}
                  <span className="text-muted-foreground font-normal"> (optional)</span>
                </Label>
                <Textarea
                  id="message"
                  placeholder={config.messagePlaceholder}
                  value={formData.message}
                  onChange={(e) => handleChange("message", e.target.value)}
                  className="min-h-[100px] bg-background border-border focus:border-primary focus:ring-primary/20 resize-none"
                />
              </div>

              <Button
                type="submit"
                className="w-full h-11 font-medium shadow-lg shadow-primary/25"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating account...
                  </>
                ) : (
                  <>
                    {config.submitLabel}
                    <span className="ml-2">{config.icon}</span>
                  </>
                )}
              </Button>

              <p className="text-xs text-muted-foreground text-center">
                By submitting, you agree to our{" "}
                <Link to="/terms" className="text-primary hover:text-primary/80">
                  Terms of Service
                </Link>{" "}
                and{" "}
                <Link to="/privacy" className="text-primary hover:text-primary/80">
                  Privacy Policy
                </Link>
              </p>
            </form>

            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link
                to="/sign-in"
                className="text-primary hover:text-primary/80 font-medium transition-colors"
              >
                Sign in
              </Link>
            </p>
          </div>
        </div>
    </div>
  );
}
