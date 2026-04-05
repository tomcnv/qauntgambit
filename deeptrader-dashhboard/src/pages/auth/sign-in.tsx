import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { z } from "zod";
import { motion } from "framer-motion";
import toast from "react-hot-toast";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Button } from "../../components/ui/button";
import Logo from "../../components/logo";
import useAuthStore from "../../store/auth-store";
import { dashboardOrigin, isDashboardHost } from "../../lib/quantgambit-url";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(6),
});

type SignInForm = z.infer<typeof schema>;
type LocationState = {
  from?: {
    pathname: string;
  };
};

export default function SignInPage() {
  const navigate = useNavigate();
  const location = useLocation() as { state?: LocationState };
  const login = useAuthStore((state) => state.login);
  const token = useAuthStore((state) => state.token);
  const loading = useAuthStore((state) => state.loading);
  const authError = useAuthStore((state) => state.error);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignInForm>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = async (values: SignInForm) => {
    try {
      await login(values);
      const redirectTo = location.state?.from?.pathname ?? "/";

      // Landing-site login should hand off to the dashboard subdomain. We pass
      // the token via URL and the dashboard stores it in localStorage.
      if (!isDashboardHost()) {
        const dash = dashboardOrigin();
        const t = token || useAuthStore.getState().token;
        if (t) {
          window.location.href = `${dash}/?auth_token=${encodeURIComponent(t)}`;
          return;
        }
        window.location.href = dash;
        return;
      }

      navigate(redirectTo);
    } catch (error) {
      const message = (error as Error).message || "Login failed";
      toast.error(message);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(96,165,250,0.2),transparent_45%),radial-gradient(circle_at_80%_0,rgba(196,181,253,0.2),transparent_35%)]" />
      <div className="absolute inset-0 bg-noise opacity-5" />
      <div className="relative z-10 flex min-h-screen items-center justify-center px-6 py-16">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-lg rounded-[32px] border border-white/10 bg-black/40 p-10 shadow-elevated backdrop-blur-2xl"
        >
          <div className="mb-10 flex flex-col items-center gap-4 text-center">
            <Logo />
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
                Operator Access
              </p>
              <h2 className="mt-2 text-3xl font-semibold text-white">Sign into Command</h2>
            </div>
          </div>

          <form className="space-y-6" onSubmit={handleSubmit(onSubmit)}>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="you@fund.com" {...register("email")} />
              {errors.email && (
                <p className="text-xs text-rose-400">{errors.email.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter secure password"
                {...register("password")}
              />
              {errors.password && (
                <p className="text-xs text-rose-400">{errors.password.message}</p>
              )}
            </div>

            <Button type="submit" size="lg" className="w-full" disabled={loading}>
              {loading ? "Authenticating..." : "Enter Dashboard"}
            </Button>
          </form>

          {authError && (
            <p className="mt-4 text-center text-sm text-rose-400">{authError}</p>
          )}

          <p className="mt-8 text-center text-sm text-muted-foreground">
            Need an account?{" "}
            <Link to="/auth/sign-up" className="text-primary hover:underline">
              Request access
            </Link>
          </p>
        </motion.div>
      </div>
    </div>
  );
}

