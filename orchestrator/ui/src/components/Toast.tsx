import { WifiOff } from 'lucide-react';

interface ToastProps {
  message: string;
}

export function Toast({ message }: ToastProps) {
  return (
    <div className="fixed bottom-6 right-6 z-50 transition-opacity duration-300">
      <div className="flex items-center gap-3 px-4 py-3 bg-red-950/90 border border-red-500/50 backdrop-blur-md text-red-200 rounded-lg shadow-xl shadow-red-900/10">
        <WifiOff className="w-5 h-5 text-red-500" />
        <span className="font-medium">{message}</span>
      </div>
    </div>
  );
}
