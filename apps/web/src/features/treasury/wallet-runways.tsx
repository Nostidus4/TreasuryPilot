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
  const num = (value: string) =>
    Number(formatUnits(value, units.decimals, { group: false }));
  const labelOf = (address: string) =>
    wallets.find((wallet) => wallet.safeAddress === address)?.label;

  return (
    <>
      {forecast.wallets.map((wallet) => (
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
      {forecast.suggestedRefills.length > 0 && (
        <Card>
          <CardHeader title={t('Suggested refills')} />
          <CardContent>
            <ul className="grid gap-3">
              {forecast.suggestedRefills.map((refill) => (
                <li
                  key={`${refill.date}-${refill.targetAddress}`}
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
          </CardContent>
        </Card>
      )}
    </>
  );
}
