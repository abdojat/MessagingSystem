import { useState } from "react";
import { Link, useLocation } from "wouter";
import { useRegister } from "../hooks/use-auth";
import { Button } from "../components/ui/button";
import { ThemeToggle } from "../components/ThemeToggle";

export default function Register() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const register = useRegister();
  const [, setLocation] = useLocation();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    register.mutate({ username, email, password }, {
      onSuccess: () => setLocation('/app')
    });
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center relative overflow-hidden bg-background">
      <div className="absolute inset-0 z-0">
        <img 
          src={`${import.meta.env.BASE_URL}images/auth-bg.png`} 
          alt="Abstract elegant background" 
          className="w-full h-full object-cover opacity-40 mix-blend-screen transform scale-105"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/80 to-transparent" />
      </div>
      <ThemeToggle className="absolute right-6 top-6 z-20 rounded-xl border border-border/70 bg-background/70 text-foreground shadow-sm backdrop-blur hover:bg-accent" />

      <div className="relative z-10 w-full max-w-md p-8">
        <div className="text-center mb-10">
          <div className="w-16 h-16 bg-gradient-to-br from-primary to-primary/60 rounded-2xl mx-auto flex items-center justify-center text-3xl font-bold text-white shadow-xl shadow-primary/30 mb-6">
            C
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Create account</h1>
          <p className="text-muted-foreground mt-2">Join ChatCore today</p>
        </div>

        <div className="bg-card/50 backdrop-blur-xl border border-border/50 p-8 rounded-3xl shadow-2xl shadow-black/50">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder="name@example.com"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder="Choose a username"
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
                placeholder="Create a password"
                required
              />
            </div>
            
            {register.isError && (
              <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-xl text-destructive text-sm font-medium">
                {(register.error as any).message || "Failed to register."}
              </div>
            )}

            <Button 
              type="submit" 
              className="w-full h-12 text-base font-semibold rounded-xl bg-gradient-to-r from-primary to-primary/90 shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5 transition-all"
              disabled={register.isPending}
            >
              {register.isPending ? "Creating account..." : "Sign up"}
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="font-semibold text-primary hover:text-primary/80 transition-colors">
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
