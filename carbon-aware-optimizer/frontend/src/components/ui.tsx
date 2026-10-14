import { AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { STATUS_STYLE } from "../utils/format";
import type { Status } from "../types";

export const StatusBadge = ({ status }: { status: Status }) => (
  <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[status]}`}>{status}</span>
);

export function Metric({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accent ? "text-leaf-400" : "text-slate-100"}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export const Loading = ({ label = "Loading…" }: { label?: string }) => (
  <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> {label}</div>
);
export const ErrorBox = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-200">
    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div className="flex-1">{message}</div>
    {onRetry && <button className="btn" onClick={onRetry}>Retry</button>}
  </div>
);
export const Empty = ({ children }: { children: ReactNode }) => <div className="p-6 text-center text-sm text-slate-500">{children}</div>;

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className={`max-h-[90vh] w-full overflow-auto rounded-xl border border-ink-600 bg-ink-900 p-5 shadow-xl outline-none ${wide ? "max-w-3xl" : "max-w-md"}`}>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2>
          <button className="btn" aria-label="Close dialog" onClick={onClose}><X className="h-4 w-4" /></button></div>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, message, confirmLabel = "Confirm", danger, onConfirm, onCancel }:
  { title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="mb-4 text-sm text-slate-300">{message}</div>
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </Modal>
  );
}

interface ToastItem { id: number; kind: "ok" | "err"; text: string }
const ToastCtx = createContext<(kind: "ok" | "err", text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((kind: "ok" | "err", text: string) => {
    const id = Date.now() + Math.random();
    setItems((i) => [...i, { id, kind, text }]);
    setTimeout(() => setItems((i) => i.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={`flex items-start gap-2 rounded-lg border p-3 text-sm shadow ${t.kind === "ok" ? "border-leaf-600 bg-ink-800" : "border-red-700 bg-red-950"}`}>
            {t.kind === "ok" ? <CheckCircle2 className="h-4 w-4 text-leaf-400" /> : <AlertTriangle className="h-4 w-4 text-red-300" />}<span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const Progress = ({ value }: { value: number }) => (
  <div className="h-2 w-full overflow-hidden rounded-full bg-ink-700" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
    <div className="h-full rounded-full bg-leaf-500 transition-all" style={{ width: `${Math.min(100, value * 100)}%` }} />
  </div>
);
