"use client";

import { useEffect, useMemo, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const initial = useMemo<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";
    return localStorage.getItem("theme-mode") === "dark" ? "dark" : "light";
  }, []);
  const [theme, setTheme] = useState<"light" | "dark">(initial);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme-mode", theme);
  }, [theme]);

  return (
    <Button size="sm" variant="ghost" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
