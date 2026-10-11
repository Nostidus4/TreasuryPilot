import { CircleDollarSign, LogOut, ShieldCheck } from 'lucide-react';
import { Outlet } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/use-auth';

export function AppLayout() {
  const { signOut } = useAuth();

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-3 font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-emerald-300">
              <CircleDollarSign aria-hidden="true" size={21} />
            </span>
            TreasuryPilot
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800 sm:flex">
              <ShieldCheck aria-hidden="true" size={14} />
              Local preview
            </span>
            <Button variant="ghost" size="sm" onClick={signOut}>
              <LogOut aria-hidden="true" size={16} />
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-12">
        <Outlet />
      </main>
    </div>
  );
}
