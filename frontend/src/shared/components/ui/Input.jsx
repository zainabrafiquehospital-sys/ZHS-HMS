'use client';

import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '@/utils/cn';

/** `type="password"` gets a built-in show/hide toggle (eye icon, right
 * side, inside the field) automatically — every password field in the
 * app (login, signup, forgot/reset-password, any future admin
 * password-setting UI) goes through this one component, so the toggle
 * lands everywhere at once rather than being reimplemented per call
 * site. Every other `type` renders exactly as before — same markup,
 * same classes, no wrapper — so this is a no-op change for the many
 * non-password inputs elsewhere in the app. */
export function Input({ className, type = 'text', ...props }) {
  const [showPassword, setShowPassword] = useState(false);
  const isPassword = type === 'password';

  const input = (
    <input
      type={isPassword && showPassword ? 'text' : type}
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        isPassword && 'pr-9',
        className,
      )}
      {...props}
    />
  );

  if (!isPassword) {
    return input;
  }

  return (
    <div className="relative">
      {input}
      <button
        type="button"
        onClick={() => setShowPassword((prev) => !prev)}
        aria-label={showPassword ? 'Hide password' : 'Show password'}
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
        disabled={props.disabled}
      >
        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}
