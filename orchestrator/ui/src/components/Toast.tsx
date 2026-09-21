// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { CheckCircle, WifiOff } from 'lucide-react';

interface ToastProps {
  message: string;
  variant?: 'error' | 'success';
}

export function Toast({ message, variant = 'error' }: ToastProps) {
  const isSuccess = variant === 'success';
  return (
    <div className="fixed bottom-6 right-6 z-50 transition-opacity duration-300" role="status" aria-live="polite">
      <div
        className={`flex items-center gap-3 px-4 py-3 backdrop-blur-md rounded-lg shadow-xl ${
          isSuccess
            ? 'bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 shadow-emerald-900/10'
            : 'bg-red-950/90 border border-red-500/50 text-red-200 shadow-red-900/10'
        }`}
      >
        {isSuccess ? <CheckCircle className="w-5 h-5 text-emerald-500" /> : <WifiOff className="w-5 h-5 text-red-500" />}
        <span className="font-medium">{message}</span>
      </div>
    </div>
  );
}
