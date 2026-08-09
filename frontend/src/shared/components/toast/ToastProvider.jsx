'use client';

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { ToastViewport } from '@/shared/components/toast/ToastViewport';

const ToastContext = createContext(null);

// Errors deliberately never auto-dismiss (Part 4's own design
// reference: "auto-dismissing except errors") — a failed action stays
// visible until the user reads it and explicitly dismisses or retries,
// never disappears on its own while they're still looking at the form
// it refers to.
const DEFAULT_DURATION_MS = { success: 5000, info: 4500, loading: null, error: null };

let _nextId = 1;

/** Shared toast provider + `useToast()` hook (Part 4.7) — one instance
 * mounted in AppProviders, available to every route including the
 * unauthenticated auth pages. Kept deliberately dependency-free (no
 * toast library — see this task's own Part 1 investigation on why:
 * this codebase consistently builds small primitives from Card/Button
 * rather than reaching for a new package, and `tailwindcss-animate`
 * already covers the animation this needs) rather than a parallel
 * state-management concept: this is plain `useState` + `setTimeout`,
 * the same complexity class as every other provider in this app. */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    // Two-phase removal: flip `exiting` first so Toast.jsx can play its
    // exit animation, then actually drop it from state once that
    // animation has had time to finish — removing immediately would
    // just make toasts vanish with no exit transition at all.
    setToasts((current) => current.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    const clearTimer = timers.current.get(id);
    if (clearTimer) {
      clearTimeout(clearTimer);
      timers.current.delete(id);
    }
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, 200);
  }, []);

  const show = useCallback(
    (variant, { title, description, duration, onRetry, spinner } = {}) => {
      const id = _nextId++;
      const resolvedDuration = duration !== undefined ? duration : DEFAULT_DURATION_MS[variant];
      const toastEntry = {
        id,
        variant,
        title,
        description,
        onRetry,
        spinner: spinner ?? variant === 'loading',
        duration: resolvedDuration,
        exiting: false,
      };
      setToasts((current) => [...current, toastEntry]);

      if (resolvedDuration) {
        const timeoutId = setTimeout(() => dismiss(id), resolvedDuration);
        timers.current.set(id, timeoutId);
      }
      return id;
    },
    [dismiss],
  );

  /** Updates an existing toast in place — the mechanism behind
   * `toast.loading(...)` resolving into a success/error without a
   * visible flicker (dismiss one, show another): a doctor/admin
   * action that starts a `loading` toast can call `update(id, {...})`
   * once the request settles, converting it to `success`/`error`
   * (including starting its auto-dismiss timer only at that point). */
  const update = useCallback(
    (id, variant, { title, description, duration, onRetry, spinner } = {}) => {
      const resolvedDuration = duration !== undefined ? duration : DEFAULT_DURATION_MS[variant];
      setToasts((current) =>
        current.map((t) =>
          t.id === id
            ? {
                ...t,
                variant,
                title,
                description,
                onRetry,
                spinner: spinner ?? variant === 'loading',
                duration: resolvedDuration,
              }
            : t,
        ),
      );
      const existingTimer = timers.current.get(id);
      if (existingTimer) clearTimeout(existingTimer);
      if (resolvedDuration) {
        const timeoutId = setTimeout(() => dismiss(id), resolvedDuration);
        timers.current.set(id, timeoutId);
      }
    },
    [dismiss],
  );

  const api = useMemo(
    () => ({
      success: (opts) => show('success', opts),
      error: (opts) => show('error', opts),
      info: (opts) => show('info', opts),
      loading: (opts) => show('loading', opts),
      dismiss,
      update,
    }),
    [show, dismiss, update],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/** `const { toast } = useToast(); toast.success({ title, description })`
 * — `toast.error({ title, description, onRetry })` for a failure with
 * a real retry action; `toast.loading({ title })` returns an id to
 * later `toast.update(id, 'success', {...})` once the operation
 * resolves. */
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider (see AppProviders.jsx).');
  }
  return { toast: context };
}
