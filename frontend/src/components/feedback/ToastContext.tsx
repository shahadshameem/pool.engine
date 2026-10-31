import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import { cn } from '../../lib/utils';
import { AlertCircle, CheckCircle, Info, X } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void;
  dismissAll: () => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider = ({ children }: { children: React.ReactNode }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const activeMessages = useRef<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dismissAll = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    activeMessages.current.clear();
    setToasts([]);
  }, []);

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    // Deduplicate identical simultaneous messages
    if (activeMessages.current.has(message)) {
      return;
    }

    const id = Math.random().toString(36).substr(2, 9);
    activeMessages.current.clear();
    activeMessages.current.add(message);

    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    // B3: Replace previous toast so at most 1 toast is visible at any time, preventing stacking/overlap
    setToasts([{ id, message, type }]);

    // Auto remove after 3.5s
    timerRef.current = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      activeMessages.current.delete(message);
    }, 3500);
  }, []);

  const removeToast = (id: string, message: string) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setToasts((prev) => prev.filter((t) => t.id !== id));
    activeMessages.current.delete(message);
  };

  return (
    <ToastContext.Provider value={{ showToast, dismissAll }}>
      {children}
      <div
        className="fixed left-0 right-0 top-[calc(1rem+env(safe-area-inset-top,0px))] z-[9999] mx-auto flex w-full max-w-md flex-col items-center gap-2 px-4 pointer-events-none transition-all duration-300"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "pointer-events-auto flex w-full items-center justify-between gap-3 rounded-[18px] p-4 shadow-[0_10px_35px_rgba(0,0,0,0.18)] animate-in slide-in-from-top-5 fade-in duration-300 border",
              toast.type === 'success' && "bg-card text-foreground border-border/80 shadow-md",
              toast.type === 'error' && "bg-destructive text-destructive-foreground border-transparent shadow-md",
              toast.type === 'warning' && "bg-amber-500/15 text-amber-900 dark:text-amber-200 border-amber-500/30 shadow-md",
              toast.type === 'info' && "bg-card text-foreground border-border/80 shadow-md"
            )}
          >
            <div className="flex items-center gap-3">
              {toast.type === 'success' && <CheckCircle className="h-5 w-5 text-[#25D366] shrink-0" />}
              {toast.type === 'error' && <AlertCircle className="h-5 w-5 shrink-0" />}
              {toast.type === 'warning' && <AlertCircle className="h-5 w-5 text-amber-500 shrink-0" />}
              {toast.type === 'info' && <Info className="h-5 w-5 text-foreground/80 shrink-0" />}
              <span className="text-[14px] font-bold tracking-tight">{toast.message}</span>
            </div>
            <button onClick={() => removeToast(toast.id, toast.message)} className="opacity-60 hover:opacity-100 p-1 cursor-pointer">
              <X className="h-4 w-4" strokeWidth={2.5} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
};