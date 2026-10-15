import { Amount } from '@/components/domain/amount';
import { Address } from '@/components/domain/chain';
import { LineSeriesChart } from '@/components/charts';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import type { Asset, Forecast, TreasuryWallet } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatUnits } from '@/lib/money';

/** One 7-day balance chart per operational wallet, plus suggested refills. */
export function WalletRunways({
  asset,
  forecast,
  units,
  wallets,
}: {
  asset: Asset;
  forecast: Forecast;
  wallets: TreasuryWallet[];
  units: { decimals: number; symbol: string };
}) {
  // Number is for chart display only; amounts elsewhere stay as base-unit strings.
  const num = (value: string) =>
    Number(formatUnits(value, units.decimals, { group: false }));
  const labelOf = (address: string) =>
    wallets.find((wallet) => wallet.safeAddress === address)?.label;

  // The O1 wallet is already charted by the 7-day runway card.
  const charted = forecast.wallets.filter((wallet) => wallet.role !== 'O1');
  if (charted.length === 0 && forecast.suggestedRefills.length === 0)
    return null;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {charted.map((wallet) => (
        <Card key={wallet.safeAddress}>
          <CardHeader
            title={t('{{wallet}} runway', { wallet: wallet.label })}
            description={t('Projected balance for the next 7 days')}
          />
          <CardContent>
            <LineSeriesChart
              data={wallet.days.map((day) => ({
                label: formatDate(day.date),
                value: num(day.balance),
                display: `${formatUnits(day.balance, units.decimals)} ${units.symbol}`,
              }))}
              references={[{ value: num(wallet.buffer), label: t('Buffer') }]}
              seriesLabel={t('Projected balance')}
              summary={t('{{wallet}} projected balance for the next 7 days', {
                wallet: wallet.label,
              })}
              xLabel={t('Day')}
            />
          </CardContent>
        </Card>
      ))}
      <Card>
        <CardHeader title={t('Suggested refills')} />
        <CardContent>
          {forecast.suggestedRefills.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('No refills suggested')}
            </p>
          ) : (
            <ul className="grid gap-3">
              {forecast.suggestedRefills.map((refill) => (
                <li
                  key={`${refill.requestId}-${refill.date}-${refill.targetAddress}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
                >
                  <span className="text-muted-foreground">
                    {formatDate(refill.date)}
                  </span>
                  <Amount asset={asset} value={refill.amount} />
                  <span className="text-muted-foreground">{t('from')}</span>
                  <Address
                    address={refill.sourceAddress}
                    label={labelOf(refill.sourceAddress)}
                  />
                  <span className="text-muted-foreground">{t('to')}</span>
                  <Address
                    address={refill.targetAddress}
                    label={labelOf(refill.targetAddress)}
                  />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
