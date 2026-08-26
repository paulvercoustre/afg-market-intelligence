import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getMarketProfile } from '@/lib/api'
import { formatUSD, formatPct, scoreBg, scoreBarColor } from '@/lib/utils'
import ScoreBadge from '@/components/ScoreBadge'
import ScoreBar from '@/components/ScoreBar'
import NextSteps from '@/components/NextSteps'

// Display label per config.NATIVE_UNIT_PRICE_BASES value (falls back to the
// raw basis string for anything not listed, e.g. a future addition there).
const PRICE_BASIS_LABELS: Record<string, string> = {
  kg: 'kg',
  'm²': 'm²',
  u: 'piece',
}

function formatUnitPrice(value: number | null, basis: string | null): string {
  const formatted = formatUSD(value, false)
  if (value == null || !basis) return formatted
  return `${formatted} /${PRICE_BASIS_LABELS[basis] ?? basis}`
}

const SCORE_DIMENSIONS = [
  { key: 'market_size', label: 'Market size', weight: 0.20 },
  { key: 'market_growth', label: 'Market growth', weight: 0.18 },
  { key: 'market_quality', label: 'Market quality', weight: 0.13 },
  { key: 'price_competitiveness', label: 'Price competitiveness', weight: 0.13 },
  { key: 'tariff', label: 'Tariff rate', weight: 0.12 },
  { key: 'afg_foothold', label: 'Afghan foothold', weight: 0.10 },
  { key: 'distance', label: 'Geographic proximity', weight: 0.10 },
  { key: 'language', label: 'Language similarity', weight: 0.04 },
] as const

export default async function MarketProfilePage(
  props: PageProps<'/discover/[hs_code]/markets/[market_code]'>,
) {
  const { hs_code, market_code } = await props.params
  const profile = await getMarketProfile(hs_code, market_code)
  if (!profile) notFound()

  // Trade figures fall back to this market's own most recent reported year
  // when computed_for_year's data hasn't landed at Comtrade yet -- flag it
  // whenever that fallback actually kicked in, so a lower score doesn't get
  // mistaken for a weak market when it's really just a reporting lag.
  const tradeDataYear = profile.trade?.trade_data_year ?? null
  const isStaleTradeData =
    tradeDataYear != null &&
    profile.computed_for_year != null &&
    tradeDataYear !== profile.computed_for_year

  // Afghanistan can genuinely have zero recorded exports here for the
  // current trade_data_year (a real signal, not a data gap) -- when that
  // happens, surface the last year it did have any, purely for context,
  // rather than showing a bare dash with no history at all.
  const afgLastExportYear = profile.trade?.afg_last_export_year ?? null
  const afgLastExportValue = profile.trade?.afg_last_export_value_usd ?? null
  const showAfgLastExport =
    profile.trade != null &&
    profile.trade.afg_export_value_usd == null &&
    afgLastExportYear != null

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-gray-400 mb-5">
        <Link href="/" className="text-[#0468B1] hover:underline">
          Products
        </Link>
        <span>/</span>
        <Link href={`/discover/${hs_code}`} className="text-[#0468B1] hover:underline">
          {profile.product_name ?? hs_code}
        </Link>
        <span>/</span>
        <span className="text-gray-600">{profile.market_name ?? market_code}</span>
      </div>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-8">
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">
            {profile.market_name ?? market_code}
          </h1>
          <p className="text-sm text-gray-400 mt-0.5">
            {profile.product_name} · HS {hs_code}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-xs text-gray-400">Opportunity score</p>
            <ScoreBadge score={profile.opportunity_score} size="lg" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column — score breakdown, trade data, competitors */}
        <div className="lg:col-span-2 space-y-6">
          {/* Score breakdown */}
          <Section title="Score breakdown">
            <div className="space-y-2.5">
              {SCORE_DIMENSIONS.map((dim) => (
                <ScoreBar
                  key={dim.key}
                  label={`${dim.label} (${(dim.weight * 100).toFixed(0)}%)`}
                  score={profile.score_breakdown[dim.key]}
                />
              ))}
            </div>
          </Section>

          {/* Trade data */}
          {profile.trade && (
            <Section title="Trade data">
              {isStaleTradeData && (
                <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-100 rounded-md px-3 py-2 mb-4">
                  This market&apos;s latest reported trade data is from {tradeDataYear}
                  {' '}(not {profile.computed_for_year}) — Comtrade hasn&apos;t published its{' '}
                  {profile.computed_for_year} figures yet, so the numbers and score below
                  reflect {tradeDataYear}.
                </p>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <StatCard
                  label="Afghan exports"
                  value={formatUSD(profile.trade.afg_export_value_usd)}
                  sub={
                    isStaleTradeData
                      ? `(${tradeDataYear} data)`
                      : showAfgLastExport
                        ? `last exported ${afgLastExportYear}: ${formatUSD(afgLastExportValue)}`
                        : undefined
                  }
                />
                <StatCard
                  label="Global market size"
                  value={formatUSD(profile.trade.global_market_size_usd)}
                  sub={isStaleTradeData ? `(${tradeDataYear} data)` : undefined}
                />
                <StatCard
                  label="Afghan market share"
                  value={formatPct(profile.trade.market_share_pct, 2, false)}
                  sub={isStaleTradeData ? `(${tradeDataYear} data)` : undefined}
                />
                <StatCard
                  label="CAGR"
                  value={formatPct(profile.trade.growth.cagr_pct)}
                  sub={`${profile.trade.growth.first_year ?? '?'}–${profile.trade.growth.last_year ?? '?'}`}
                />
                <StatCard
                  label="Year-on-year growth"
                  value={formatPct(profile.trade.growth.yoy_growth_pct)}
                />
                {profile.trade.afg_supplier_rank != null && (
                  <StatCard
                    label="Afghan supplier rank"
                    value={`#${profile.trade.afg_supplier_rank}`}
                    sub={isStaleTradeData ? `(${tradeDataYear} data)` : undefined}
                  />
                )}
              </div>

              {/* Price */}
              <div className="mt-4 pt-4 border-t border-gray-100">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                  Pricing
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <StatCard
                    label="Afghan unit price"
                    value={formatUnitPrice(profile.trade.price.unit_price_usd, profile.trade.price.price_basis)}
                  />
                  <StatCard
                    label="Market avg price"
                    value={formatUnitPrice(profile.trade.price.market_avg_price_usd, profile.trade.price.price_basis)}
                  />
                  <StatCard
                    label="vs market avg"
                    value={formatPct(profile.trade.price.price_vs_market_pct)}
                  />
                  <StatCard
                    label="Competitiveness"
                    value={profile.trade.price.price_competitiveness ?? '—'}
                    sub={
                      profile.trade.price.price_competitiveness == null
                        ? 'No unit data for comparison'
                        : undefined
                    }
                    highlight={profile.trade.price.price_competitiveness != null}
                  />
                </div>
                {profile.trade.price.price_competitiveness == null && (
                  <p className="text-[11px] text-gray-400 italic mt-2">
                    Afghanistan or its competitors didn&apos;t report a comparable weight-based unit
                    price for this market — price competitiveness isn&apos;t factored into the
                    opportunity score for this row (treated as neutral).
                  </p>
                )}
              </div>
            </Section>
          )}

          {/* Competitors */}
          {profile.competitors.length > 0 && (
            <Section title="Top competitors in this market">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-2 pr-4 font-semibold text-gray-500">Supplier</th>
                      <th className="text-right py-2 pr-4 font-semibold text-gray-500">
                        Export value
                      </th>
                      <th className="text-right py-2 font-semibold text-gray-500">
                        Market share
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {profile.competitors.map((c) => (
                      <tr key={c.supplier_code} className="hover:bg-gray-50">
                        <td className="py-2 pr-4 font-medium text-gray-800">{c.supplier_name}</td>
                        <td className="py-2 pr-4 text-right tabular-nums text-gray-600">
                          {formatUSD(c.trade_value_usd)}
                        </td>
                        <td className="py-2 text-right">
                          {c.market_share_pct != null ? (
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-16 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className="h-full bg-[#0468B1] rounded-full"
                                  style={{
                                    width: `${Math.min(100, c.market_share_pct)}%`,
                                  }}
                                />
                              </div>
                              <span className="tabular-nums text-gray-600 w-12 text-right">
                                {c.market_share_pct.toFixed(1)}%
                              </span>
                            </div>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}
        </div>

        {/* Right column — context + next steps */}
        <div className="space-y-6">
          {/* Market context */}
          <Section title="Market context">
            <div className="space-y-2.5 text-xs">
              <ContextRow
                label="GDP per capita"
                value={formatUSD(profile.context.gdp_per_capita_usd, false)}
              />
              <ContextRow
                label="Logistics (LPI)"
                value={
                  profile.context.lpi_score != null
                    ? `${profile.context.lpi_score.toFixed(2)} / 5`
                    : '—'
                }
                dataYear={profile.context.lpi_score_year}
                currentYear={profile.computed_for_year}
              />
              <ContextRow
                label="Regulatory quality"
                value={
                  profile.context.regulatory_quality != null
                    ? profile.context.regulatory_quality.toFixed(2)
                    : '—'
                }
                dataYear={profile.context.regulatory_quality_year}
                currentYear={profile.computed_for_year}
              />
              <ContextRow
                label="Political stability"
                value={
                  profile.context.political_stability != null
                    ? profile.context.political_stability.toFixed(2)
                    : '—'
                }
                dataYear={profile.context.political_stability_year}
                currentYear={profile.computed_for_year}
              />
              {profile.context.tariff_rate_pct != null && (
                <ContextRow
                  label={`Tariff rate (${profile.context.tariff_indicator ?? 'MFN'})`}
                  value={`${profile.context.tariff_rate_pct.toFixed(1)}%`}
                  highlight={profile.context.tariff_rate_pct >= 15}
                  dataYear={profile.context.tariff_year}
                  currentYear={profile.computed_for_year}
                />
              )}
            </div>
          </Section>

          {/* Next steps */}
          {profile.next_steps.length > 0 && (
            <Section title="Recommended next steps">
              <NextSteps steps={profile.next_steps} />
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wider">
        {title}
      </h2>
      {children}
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string
  value: string
  sub?: string
  highlight?: boolean
}) {
  return (
    <div>
      <p className="text-xs text-gray-400 mb-0.5">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? 'text-[#0468B1]' : 'text-gray-900'}`}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
    </div>
  )
}

function ContextRow({
  label,
  value,
  highlight,
  dataYear,
  currentYear,
}: {
  label: string
  value: string
  highlight?: boolean
  dataYear?: number | null
  currentYear?: number | null
}) {
  const isStale = dataYear != null && currentYear != null && dataYear !== currentYear
  return (
    <div className="flex justify-between gap-2 py-1 border-b border-gray-50 last:border-0">
      <span className="text-gray-500">{label}</span>
      <span className={`font-medium tabular-nums ${highlight ? 'text-red-600' : 'text-gray-800'}`}>
        {value}
        {isStale && (
          <span
            className="text-amber-500 font-normal ml-1"
            title={`This value is from ${dataYear}, the most recent year reported -- not ${currentYear}.`}
          >
            ({dataYear})
          </span>
        )}
      </span>
    </div>
  )
}
