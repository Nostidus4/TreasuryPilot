import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleDot,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/use-auth';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { startPreviewSession } = useAuth();

  const preview = () => {
    startPreviewSession();
    const requestedPage = (location.state as { from?: Location } | null)?.from;
    navigate(
      requestedPage
        ? `${requestedPage.pathname}${requestedPage.search}${requestedPage.hash}`
        : '/',
      { replace: true },
    );
  };

  return (
    <main className="relative isolate min-h-screen overflow-hidden bg-[#f7f9fe] text-[#162448]">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_14%_8%,rgba(72,126,255,0.13),transparent_34%),radial-gradient(ellipse_at_86%_92%,rgba(42,91,226,0.08),transparent_34%)]"
      />

      <div className="mx-auto grid min-h-screen max-w-[1600px] lg:grid-cols-[1.08fr_0.92fr]">
        <section className="relative flex min-h-[620px] flex-col overflow-hidden px-6 py-7 sm:px-10 sm:py-9 lg:min-h-screen lg:px-[clamp(3rem,8vw,8.5rem)] lg:py-10">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-[#e8f0ff] via-[#f2f6ff] to-[#e8efff]"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-32 top-24 -z-10 h-[26rem] w-[26rem] rounded-full border border-blue-300/25 sm:right-[-4rem] lg:right-[-10rem] lg:top-36 lg:h-[38rem] lg:w-[38rem]"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-20 top-40 -z-10 h-[20rem] w-[20rem] rounded-full border border-blue-300/20 sm:right-4 lg:right-[-4rem] lg:top-52 lg:h-[27rem] lg:w-[27rem]"
          />

          <Link
            aria-label="TreasuryPilot home"
            className="inline-flex w-fit items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-4 focus-visible:ring-offset-[#edf3ff]"
            to="/login"
          >
            <span className="grid h-11 w-11 place-items-center rounded-[15px] bg-[#2459e8] text-white shadow-[0_10px_22px_rgba(36,89,232,0.24)]">
              <ShieldCheck aria-hidden="true" size={23} strokeWidth={1.8} />
            </span>
            <span className="text-[17px] font-bold tracking-[-0.04em] text-[#18264a]">
              TreasuryPilot
            </span>
          </Link>

          <div className="mx-auto mt-16 w-full max-w-[660px] sm:mt-20 lg:my-auto lg:mt-0 lg:py-14">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-200/80 bg-white/65 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.15em] text-[#4566a5] shadow-sm shadow-blue-900/[0.03]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#2861ee] shadow-[0_0_0_3px_rgba(40,97,238,0.12)]" />
              Treasury operations workspace
            </div>

            <h1 className="max-w-[620px] text-[clamp(2.8rem,5.4vw,5rem)] font-semibold leading-[0.99] tracking-[-0.065em] text-[#17264a]">
              Treasury operations,
              <br />
              <span className="bg-gradient-to-r from-[#2460eb] to-[#5481f5] bg-clip-text text-transparent">
                under control.
              </span>
            </h1>
            <p className="mt-6 max-w-[550px] text-[15px] leading-7 text-[#63779e] sm:text-base sm:leading-8">
              A calm command center for stablecoin payments. Review obligations,
              plan execution, and keep every movement inside human-approved
              policy.
            </p>

            <div className="mt-9 overflow-hidden rounded-[26px] border border-white/90 bg-white/90 p-5 shadow-[0_24px_70px_rgba(46,80,145,0.12)] ring-1 ring-blue-950/[0.04] backdrop-blur sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-[#1d2c50]">
                    <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#edf3ff] text-[#2c62e9]">
                      <ShieldCheck aria-hidden="true" size={17} />
                    </span>
                    Acme Treasury
                  </div>
                  <div className="mt-5 flex items-baseline gap-2.5">
                    <span className="text-[clamp(2rem,4vw,2.65rem)] font-semibold leading-none tracking-[-0.06em] text-[#162448]">
                      1,250,000
                    </span>
                    <span className="text-sm font-bold tracking-tight text-[#51658d]">
                      USDC
                    </span>
                  </div>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700">
                  <Check aria-hidden="true" size={13} strokeWidth={2.5} />
                  Mandate active
                </span>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#8191ae]">
                <span>Illustrative demo balance</span>
                <span aria-hidden="true" className="text-[#c2cce0]">
                  ·
                </span>
                <span className="inline-flex items-center gap-1.5 font-medium text-[#59709c]">
                  <CircleDot
                    aria-hidden="true"
                    size={12}
                    className="text-[#2b65ee]"
                  />
                  Sepolia testnet
                </span>
              </div>

              <div className="my-5 h-px bg-[#eaf0fa]" />
              <div className="grid grid-cols-3 gap-3 sm:gap-5">
                <div>
                  <p className="text-[11px] font-medium text-[#8292ae]">
                    Approved
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#223254]">
                    12 invoices
                  </p>
                </div>
                <div>
                  <p className="text-[11px] font-medium text-[#8292ae]">
                    Ready to pay
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#223254]">
                    8 payments
                  </p>
                </div>
                <div>
                  <p className="text-[11px] font-medium text-[#8292ae]">
                    Reserve
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#223254]">
                    Maintained
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-5 flex items-start gap-3 rounded-2xl border border-blue-100/80 bg-white/45 px-4 py-3.5 text-sm text-[#526991]">
              <LockKeyhole
                aria-hidden="true"
                className="mt-0.5 shrink-0 text-[#3268e7]"
                size={16}
              />
              <div>
                <h2 className="text-sm font-semibold text-[#24365b]">
                  Human approval stays in control.
                </h2>
                <p className="mt-0.5 leading-6">
                  Execution is bounded by your mandate and on-chain checks.
                </p>
              </div>
            </div>
          </div>

          <p className="mt-12 text-xs font-medium tracking-wide text-[#8a9ab6] lg:mt-0">
            Built for transparent, policy-bound treasury workflows.
          </p>
        </section>

        <section className="relative flex min-h-[560px] items-center justify-center border-t border-[#e9eef7] bg-white px-6 py-16 sm:px-10 lg:min-h-screen lg:border-l lg:border-t-0 lg:px-12">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 left-0 hidden w-px bg-gradient-to-b from-transparent via-blue-100 to-transparent lg:block"
          />
          <div className="w-full max-w-[440px]">
            <div className="mb-7 grid h-[50px] w-[50px] place-items-center rounded-[17px] bg-[#edf3ff] text-[#2861eb] ring-1 ring-[#dfe9ff]">
              <LockKeyhole aria-hidden="true" size={21} strokeWidth={1.8} />
            </div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.17em] text-[#6680b1]">
              Your workspace awaits
            </p>
            <h2 className="text-3xl font-semibold tracking-[-0.055em] text-[#17264a] sm:text-[2.45rem]">
              Welcome back
            </h2>
            <p className="mt-3 max-w-sm text-sm leading-6 text-[#7b8ba8]">
              Sign-in by email is coming soon. Open the guided preview to
              explore the TreasuryPilot workspace.
            </p>

            <div className="mt-9 rounded-2xl border border-[#e5ebf5] bg-[#fbfcff] p-4 sm:p-5">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#eaf1ff] text-[#2861eb]">
                  <ArrowUpRight aria-hidden="true" size={16} />
                </span>
                <div>
                  <p className="text-sm font-semibold text-[#27385c]">
                    Interactive product preview
                  </p>
                  <p className="mt-1 text-xs leading-5 text-[#8291aa]">
                    Explore a sample treasury workspace using fictional data on
                    Sepolia testnet.
                  </p>
                </div>
              </div>

              <Button
                className="mt-5 h-12 w-full justify-between rounded-xl bg-[#285ee9] px-5 text-sm font-semibold text-white shadow-[0_10px_22px_rgba(40,94,233,0.2)] hover:bg-[#1f50d4] focus-visible:ring-[#285ee9]"
                onClick={preview}
              >
                Preview application shell
                <ArrowRight aria-hidden="true" size={17} />
              </Button>
            </div>

            <div className="mt-6 flex items-start gap-2.5 text-xs leading-5 text-[#8291aa]">
              <LockKeyhole
                aria-hidden="true"
                className="mt-0.5 shrink-0 text-[#97a7c2]"
                size={14}
              />
              <p>
                This preview does not connect a wallet or submit transactions.
                Sign-in is not active yet.
              </p>
            </div>

            <div className="mt-10 flex items-center gap-3 border-t border-[#edf1f7] pt-5 text-[11px] font-medium text-[#8b9ab4]">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-[#2fbd92]" />
                Demo environment
              </span>
              <span aria-hidden="true" className="text-[#c5cfdf]">
                ·
              </span>
              <span>Sepolia testnet</span>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
