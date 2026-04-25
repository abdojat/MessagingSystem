import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "./ui/button";

interface ThemeToggleProps {
  className?: string;
}

interface OverlayState {
  x: number;
  y: number;
  radius: number;
}

const THEME_ANIMATION_MS = 550;
const DARK_THEME_OVERLAY =
  "radial-gradient(circle at 20% 20%, hsl(234 89% 74% / 0.22), transparent 30%), radial-gradient(circle at 82% 14%, hsl(186 92% 44% / 0.14), transparent 26%), linear-gradient(165deg, hsl(232 23% 7%), hsl(228 18% 5%))";

export function ThemeToggle({ className }: ThemeToggleProps) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [overlay, setOverlay] = useState<OverlayState | null>(null);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const isDark = mounted ? resolvedTheme !== "light" : true;

  function applyThemeClass(theme: "light" | "dark") {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
  }

  async function handleToggle(event: React.MouseEvent<HTMLButtonElement>) {
    if (!mounted || overlay) {
      return;
    }

    const nextTheme = isDark ? "light" : "dark";
    const button = event.currentTarget;
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;

    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    );

    if (nextTheme === "dark") {
      setOverlay({ x, y, radius: 0 });

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setOverlay({ x, y, radius: endRadius });
        });
      });

      timeoutRef.current = window.setTimeout(() => {
        applyThemeClass("dark");
        setTheme("dark");
        setOverlay(null);
        timeoutRef.current = null;
      }, THEME_ANIMATION_MS);

      return;
    }

    applyThemeClass("light");
    setTheme("light");
    setOverlay({ x, y, radius: endRadius });

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setOverlay({ x, y, radius: 0 });
      });
    });

    timeoutRef.current = window.setTimeout(() => {
      setOverlay(null);
      timeoutRef.current = null;
    }, THEME_ANIMATION_MS);
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={className}
        onClick={handleToggle}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      >
        {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>
      {overlay && typeof document !== "undefined"
        ? createPortal(
            <div
              aria-hidden="true"
              className="pointer-events-none fixed inset-0 z-[9999]"
              style={{
                background: DARK_THEME_OVERLAY,
                clipPath: `circle(${overlay.radius}px at ${overlay.x}px ${overlay.y}px)`,
                transition: `clip-path ${THEME_ANIMATION_MS}ms cubic-bezier(0.22, 1, 0.36, 1)`,
              }}
            />,
            document.body,
          )
        : null}
    </>
  );
}
