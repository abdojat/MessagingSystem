export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 256;

export type PasswordRequirementKey =
  | "minimumLength"
  | "uppercase"
  | "lowercase"
  | "number"
  | "special"
  | "noWhitespace";

export type PasswordRequirement = {
  key: PasswordRequirementKey;
  met: boolean;
};

const SPECIAL_CHARACTER_PATTERN = /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/;

export function getPasswordRequirements(password: string): PasswordRequirement[] {
  return [
    { key: "minimumLength", met: password.length >= PASSWORD_MIN_LENGTH },
    { key: "uppercase", met: /[A-Z]/.test(password) },
    { key: "lowercase", met: /[a-z]/.test(password) },
    { key: "number", met: /[0-9]/.test(password) },
    { key: "special", met: SPECIAL_CHARACTER_PATTERN.test(password) },
    { key: "noWhitespace", met: !/\s/.test(password) },
  ];
}

export function isStrongPassword(password: string): boolean {
  return (
    password.length <= PASSWORD_MAX_LENGTH &&
    getPasswordRequirements(password).every((requirement) => requirement.met)
  );
}
