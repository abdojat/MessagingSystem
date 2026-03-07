"use client";

import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api-client";
import { setTokenPair, useAuthStore } from "@/store/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

const loginSchema = z.object({
  username_or_email: z.string().min(1, "Username or email is required"),
  password: z.string().min(8, "Password must be at least 8 chars"),
});

const registerSchema = z.object({
  username: z.string().min(3).max(64),
  email: z.string().email().optional().or(z.literal("")),
  password: z.string().min(8).max(256),
});

type LoginValues = z.infer<typeof loginSchema>;
type RegisterValues = z.infer<typeof registerSchema>;

export function LoginForm() {
  const router = useRouter();
  const rememberMe = useAuthStore((s) => s.rememberMe);
  const setRememberMe = useAuthStore((s) => s.setRememberMe);
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { username_or_email: "", password: "" } });

  const loginMutation = useMutation({
    mutationFn: api.login,
    onSuccess: async (tokenPair) => {
      setTokenPair(tokenPair, { rememberMe });
      await api.me();
      router.replace("/app");
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(error.message);
        return;
      }
      toast.error("Login failed");
    },
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <h1 className="text-xl font-semibold">Sign in</h1>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={form.handleSubmit((values) => loginMutation.mutate(values))}>
          <div>
            <Input placeholder="Username or email" {...form.register("username_or_email")} />
            {form.formState.errors.username_or_email ? <p className="mt-1 text-xs text-red-500">{form.formState.errors.username_or_email.message}</p> : null}
          </div>
          <div>
            <Input placeholder="Password" type="password" {...form.register("password")} />
            {form.formState.errors.password ? <p className="mt-1 text-xs text-red-500">{form.formState.errors.password.message}</p> : null}
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="h-4 w-4"
            />
            Keep me logged in
          </label>
          <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
            {loginMutation.isPending ? "Signing in..." : "Login"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function RegisterForm() {
  const router = useRouter();
  const form = useForm<RegisterValues>({ resolver: zodResolver(registerSchema), defaultValues: { username: "", email: "", password: "" } });

  const registerMutation = useMutation({
    mutationFn: api.register,
    onSuccess: () => {
      toast.success("Registration successful. Please log in.");
      router.push("/login");
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(error.message);
        return;
      }
      toast.error("Registration failed");
    },
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <h1 className="text-xl font-semibold">Create account</h1>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((values) =>
            registerMutation.mutate({
              username: values.username,
              email: values.email || undefined,
              password: values.password,
            }),
          )}
        >
          <div>
            <Input placeholder="Username" {...form.register("username")} />
            {form.formState.errors.username ? <p className="mt-1 text-xs text-red-500">{form.formState.errors.username.message}</p> : null}
          </div>
          <div>
            <Input placeholder="Email (optional)" type="email" {...form.register("email")} />
            {form.formState.errors.email ? <p className="mt-1 text-xs text-red-500">{form.formState.errors.email.message}</p> : null}
          </div>
          <div>
            <Input placeholder="Password" type="password" {...form.register("password")} />
            {form.formState.errors.password ? <p className="mt-1 text-xs text-red-500">{form.formState.errors.password.message}</p> : null}
          </div>
          <Button type="submit" className="w-full" disabled={registerMutation.isPending}>
            {registerMutation.isPending ? "Creating..." : "Register"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

