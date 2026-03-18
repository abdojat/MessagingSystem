import { useState } from "react";
import { Link, useLocation } from "wouter";
import { useLogin } from "../hooks/use-auth";
import { Button } from "../components/ui/button";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();
  const [, setLocation] = useLocation();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    login.mutate({ username_or_email: username, password }, {
      onSuccess: () => setLocation('/app')
    });
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center relative overflow-hidden bg-background">
      {/* Background Image Layer */}
      <div className="absolute inset-0 z-0">
        <img 
          src={`${import.meta.env.BASE_URL}images/auth-bg.png`} 
          alt="Abstract elegant background" 
          className="w-full h-full object-cover opacity-40 mix-blend-screen"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/80 to-transparent" />
      </div>

      <div className="relative z-10 w-full max-w-md p-8">
        <div className="text-center mb-10">
          <div className="w-16 h-16 bg-gradient-to-br from-primary to-primary/60 rounded-2xl mx-auto flex items-center justify-center text-3xl font-bold text-white shadow-xl shadow-primary/30 mb-6">
            C
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Welcome back</h1>
          <p className="text-muted-foreground mt-2">Sign in to continue your conversations</p>
        </div>

        <div className="bg-card/50 backdrop-blur-xl border border-border/50 p-8 rounded-3xl shadow-2xl shadow-black/50">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder="Enter your username"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder="Enter your password"
                required
              />
            </div>
            
            {login.isError && (
              <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-xl text-destructive text-sm font-medium">
                {(login.error as any).message || "Failed to login. Please check your credentials."}
              </div>
            )}

            <Button 
              type="submit" 
              className="w-full h-12 text-base font-semibold rounded-xl bg-gradient-to-r from-primary to-primary/90 shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5 transition-all"
              disabled={login.isPending}
            >
              {login.isPending ? "Signing in..." : "Sign in"}
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            Don't have an account?{" "}
            <Link href="/register" className="font-semibold text-primary hover:text-primary/80 transition-colors">
              Create one
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
