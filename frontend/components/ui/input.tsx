import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-sm outline-none ring-offset-2 placeholder:text-slate-400 focus:ring-2 focus:ring-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:placeholder:text-slate-500",
        className,
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

