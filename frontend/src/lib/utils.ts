import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

// Combines conditional CSS class names; frontend components and services use it as a shared utility.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
