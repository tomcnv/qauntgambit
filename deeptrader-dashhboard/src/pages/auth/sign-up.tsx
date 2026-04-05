import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import toast from "react-hot-toast";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Button } from "../../components/ui/button";
import useAuthStore from "../../store/auth-store";
import Logo from "../../components/logo";
import { dashboardOrigin, isDashboardHost } from "../../lib/quantgambit-url";

const schema = z.object({
  firstName: z.string().min(2, "First name is required"),
  lastName: z.string().min(2, "Last name is required"),
  username: z.string().min(3, "Username must be at least 3 characters"),
  email: z.string().email(),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

type SignUpForm = z.infer<typeof schema>;

export default function SignUpPage() {
  const navigate = useNavigate();
  const registerAccount = useAuthStore((state) => state.register);
  const token = useAuthStore((state) => state.token);
  const loading = useAuthStore((state) => state.loading);
  const authError = useAuthStore((state) => state.error);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignUpForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      firstName: "",
      lastName: "",
      username: "",
      email: "",
      password: "",
    },
  });

  const onSubmit = async (values: SignUpForm) => {
    try {
      await registerAccount(values);

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

      navigate("/");
    } catch (error) {
      const message = (error as Error).message || "Registration failed";
      toast.error(message);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(99,102,241,.2),transparent_45%)]" />
      <div className="relative z-10 flex min-h-screen items-center justify-center px-6 py-16">
        <div className="w-full max-w-3xl space-y-8 rounded-[32px] border border-white/10 bg-black/40 p-10 shadow-elevated backdrop-blur-2xl">
          <div className="flex flex-col gap-2">
            <Logo />
            <p className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
              Request Early Access
            </p>
            <h2 className="text-4xl font-semibold text-white">Provision your control tower</h2>
          </div>

          <form className="grid gap-6 md:grid-cols-2" onSubmit={handleSubmit(onSubmit)}>
            <div className="space-y-2">
              <Label htmlFor="firstName">First name</Label>
              <Input id="firstName" placeholder="Jane" {...register("firstName")} />
              {errors.firstName && (
                <p className="text-xs text-rose-400">{errors.firstName.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="lastName">Last name</Label>
              <Input id="lastName" placeholder="Doe" {...register("lastName")} />
              {errors.lastName && (
                <p className="text-xs text-rose-400">{errors.lastName.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="username">Operator handle</Label>
              <Input id="username" placeholder="atlas.ops" {...register("username")} />
              {errors.username && (
                <p className="text-xs text-rose-400">{errors.username.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="ops@fund.com" {...register("email")} />
              {errors.email && (
                <p className="text-xs text-rose-400">{errors.email.message}</p>
              )}
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Create a strong passphrase"
                {...register("password")}
              />
              {errors.password && (
                <p className="text-xs text-rose-400">{errors.password.message}</p>
              )}
            </div>
            <div className="md:col-span-2">
              <Button type="submit" size="lg" className="w-full" disabled={loading}>
                {loading ? "Provisioning workspace..." : "Request Operator Access"}
              </Button>
            </div>
          </form>

          {authError && (
            <p className="text-center text-sm text-rose-400">{authError}</p>
          )}

          <p className="text-center text-sm text-muted-foreground">
            Already have access?{" "}
            <Link to="/auth/sign-in" className="text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

