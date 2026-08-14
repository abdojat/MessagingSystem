"use client";

import { CheckCircle2, Circle } from "lucide-react";
import { useTranslations } from "next-intl";

import { getPasswordRequirements } from "@/lib/password-policy";

type PasswordRequirementsProps = {
  password: string;
  id?: string;
};

export function PasswordRequirements({ password, id = "password-requirements" }: PasswordRequirementsProps) {
  const t = useTranslations("passwordPolicy");
  const requirements = getPasswordRequirements(password);

  return (
    <div id={id} className="mt-3 rounded-xl border border-border/60 bg-background/50 p-3" aria-live="polite">
      <p className="text-xs font-medium text-foreground">{t("title")}</p>
      <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
        {requirements.map((requirement) => (
          <li
            key={requirement.key}
            className={requirement.met ? "flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400" : "flex items-center gap-2 text-xs text-muted-foreground"}
          >
            {requirement.met ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            ) : (
              <Circle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            )}
            <span>{t(requirement.key)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
