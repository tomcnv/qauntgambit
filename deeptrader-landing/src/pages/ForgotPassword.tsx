import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, Mail, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import quantGambitDark from "@/assets/quantgambit-dark.png";
import quantGambitLight from "@/assets/quantgambit-light.png";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains("dark"));
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitted(true);
  };

  const logo = isDark ? quantGambitDark : quantGambitLight;

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <div className="w-full max-w-md space-y-8">
        {/* Logo */}
        <div className="flex justify-center">
          <Link to="/">
            <img src={logo} alt="QuantGambit" className="h-10 w-auto" />
          </Link>
        </div>

        {!isSubmitted ? (
          <>
            <div className="space-y-2 text-center">
              <div className="mx-auto w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-6">
                <Mail className="h-7 w-7 text-primary" />
              </div>
              <h2 className="text-2xl font-display font-semibold text-foreground">
                Reset your password
              </h2>
              <p className="text-muted-foreground">
                Enter your email address and we'll send you instructions to reset your password.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-sm font-medium">
                  Email address
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-11 bg-background border-border focus:border-primary focus:ring-primary/20"
                  required
                />
              </div>

              <Button
                type="submit"
                className="w-full h-11 font-medium shadow-lg shadow-primary/25"
              >
                Send reset link
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </form>
          </>
        ) : (
          <div className="space-y-6 text-center">
            <div className="mx-auto w-14 h-14 rounded-2xl bg-emerald-500/10 flex items-center justify-center">
              <CheckCircle2 className="h-7 w-7 text-emerald-500" />
            </div>
            <div className="space-y-2">
              <h2 className="text-2xl font-display font-semibold text-foreground">
                Check your email
              </h2>
              <p className="text-muted-foreground">
                We've sent password reset instructions to{" "}
                <span className="text-foreground font-medium">{email}</span>
              </p>
            </div>
            <div className="pt-4 space-y-3">
              <Button
                variant="outline"
                className="w-full h-11 font-medium"
                onClick={() => setIsSubmitted(false)}
              >
                Try a different email
              </Button>
            </div>
          </div>
        )}

        <div className="flex justify-center">
          <Link
            to="/sign-in"
            className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
