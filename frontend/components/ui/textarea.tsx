import * as React from "react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          "min-h-[80px] w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none ring-offset-2 placeholder:text-slate-400 focus:ring-2 focus:ring-slate-500 dark:border-slate-700 dark:bg-slate-900",
          className,
        )}
        {...props}
      />
    );
  },
);
Textarea.displayName = "Textarea";

