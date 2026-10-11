import { ArrowRight, LockKeyhole } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/use-auth';

export function LoginPage() {
  const navigate = useNavigate();
  const { startPreviewSession } = useAuth();

  const preview = () => {
    startPreviewSession();
    navigate('/', { replace: true });
  };

  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-white">
      <section className="w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur">
        <div className="mb-8 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-400 text-slate-950">
          <LockKeyhole aria-hidden="true" size={24} />
        </div>
        <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-emerald-300">
          TreasuryPilot
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          Human approval. Enforced execution.
        </h1>
        <p className="mt-4 text-sm leading-6 text-slate-300">
          Magic-link authentication is implemented by WEB-002. Use the preview
          session to verify this application shell.
        </p>
        <Button className="mt-8 w-full" onClick={preview}>
          Preview application shell
          <ArrowRight aria-hidden="true" size={18} />
        </Button>
      </section>
    </main>
  );
}
