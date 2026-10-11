type EmptyStateProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export function EmptyState({ eyebrow, title, description }: EmptyStateProps) {
  return (
    <section className="rounded-3xl border border-dashed border-slate-300 bg-white p-12 text-center shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-700">
        {eyebrow}
      </p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mx-auto mt-4 max-w-xl text-sm leading-6 text-slate-600">
        {description}
      </p>
    </section>
  );
}
