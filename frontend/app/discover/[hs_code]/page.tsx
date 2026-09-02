import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getDiscoveryResult } from '@/lib/api'
import { formatUSD, formatPct } from '@/lib/utils'
import ScoreBadge from '@/components/ScoreBadge'
import ScoreBar from '@/components/ScoreBar'

const SCORE_DIMENSIONS = [
  { key: 'market_size', label: 'Market size', weight: 0.20 },
  { key: 'market_growth', label: 'Market growth', weight: 0.18 },
  { key: 'market_quality', label: 'Market quality', weight: 0.13 },
  { key: 'price_competitiveness', label: 'Price', weight: 0.13 },
  { key: 'tariff', label: 'Tariff', weight: 0.12 },
  { key: 'afg_foothold', label: 'Afghan foothold', weight: 0.10 },
  { key: 'distance', label: 'Proximity', weight: 0.10 },
  { key: 'language', label: 'Language', weight: 0.04 },
] as const

export default async function DiscoverPage(props: PageProps<'/discover/[hs_code]'>) {
  const { hs_code } = await props.params
  const searchParams = await props.searchParams
  const minScore = searchParams?.min_score ? Number(searchParams.min_score) : undefined

  const result = await getDiscoveryResult(hs_code, minScore)
  if (!result) notFound()

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <Link href="/" className="text-xs text-[#0468B1] hover:underline mb-4 inline-block">
        ← All products
      </Link>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">{result.product_name}</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            HS {result.hs_code} · {result.total_markets_scored} markets scored ·{' '}
            {result.computed_for_year}
          </p>
        </div>
        <MinScoreFilter current={minScore} hsCode={hs_code} />
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-4 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> ≥ 70 High
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-amber-400 inline-block" /> 40–70 Moderate
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-red-400 inline-block" /> &lt; 40 Low
        </span>
      </div>

      {result.markets.length === 0 ? (
        <p className="text-gray-400 text-sm py-12 text-center">
          No markets match your filter. Try lowering the minimum score.
        </p>
      ) : (
        <div className="space-y-3">
          {result.markets.map((market) => (
            <div
              key={market.market_code}
              className="bg-white rounded-xl border border-gray-200 p-4 hover:border-[#0468B1]/40 hover:shadow-sm transition-all"
            >
              <div className="flex flex-col xl:flex-row xl:items-center gap-4">
                {/* Rank + name + score */}
                <div className="flex items-center gap-3 min-w-0 xl:w-64 shrink-0">
                  <span className="text-sm font-bold text-gray-300 w-6 text-right shrink-0">
                    {market.rank}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-sm text-gray-900 truncate">
                      {market.market_name ?? market.market_code}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {market.tariff_rate_pct != null && (
                        <span className="text-[10px] text-gray-400">
                          {market.tariff_rate_pct.toFixed(1)}% tariff
                          {market.context.tariff_year != null &&
                            market.context.tariff_year !== result.computed_for_year && (
                              <span
                                className="text-amber-500 ml-0.5"
                                title={`Tariff rate is from ${market.context.tariff_year}, not ${result.computed_for_year} -- WITS lags behind trade data.`}
                              >
                                ({market.context.tariff_year})
                              </span>
                            )}
                        </span>
                      )}
                    </div>
                  </div>
                  <ScoreBadge score={market.opportunity_score} />
                </div>

                {/* Score bars */}
                <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {SCORE_DIMENSIONS.map((dim) => (
                    <ScoreBar
                      key={dim.key}
                      label={dim.label}
                      score={market.score_breakdown[dim.key]}
                      weight={dim.weight}
                      displayValue={
                        dim.key === 'tariff' && market.tariff_rate_pct != null
                          ? `${market.tariff_rate_pct.toFixed(1)}%`
                          : undefined
                      }
                    />
                  ))}
                </div>

                {/* Key metrics */}
                <div className="xl:w-48 shrink-0 text-xs space-y-1.5">
                  <MetricRow
                    label="Global imports"
                    value={formatUSD(market.global_market_size_usd)}
                    staleYear={
                      market.trade_data_year != null && market.trade_data_year !== result.computed_for_year
                        ? market.trade_data_year
                        : undefined
                    }
                  />
                  <MetricRow
                    label="Afghan exports"
                    value={formatUSD(market.afg_export_value_usd)}
                    staleYear={
                      market.trade_data_year != null && market.trade_data_year !== result.computed_for_year
                        ? market.trade_data_year
                        : undefined
                    }
                    lastKnown={
                      market.afg_export_value_usd == null && market.afg_last_export_year != null
                        ? { year: market.afg_last_export_year, value: market.afg_last_export_value_usd }
                        : undefined
                    }
                  />
                  <MetricRow label="CAGR" value={formatPct(market.cagr_pct)} />
                  <MetricRow
                    label="Market share"
                    value={formatPct(market.market_share_pct, 2, false)}
                  />
                </div>

                {/* CTA */}
                <div className="xl:w-28 shrink-0">
                  <Link
                    href={`/discover/${hs_code}/markets/${market.market_code}`}
                    className="block text-center text-xs font-semibold py-2 px-3 rounded-lg border border-[#0468B1] text-[#0468B1] hover:bg-[#0468B1] hover:text-white transition-colors"
                  >
                    Full profile →
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MetricRow({
  label,
  value,
  staleYear,
  lastKnown,
}: {
  label: string
  value: string
  staleYear?: number
  lastKnown?: { year: number; value: number | null }
}) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-700 tabular-nums">
        {value}
        {staleYear != null && (
          <span
            className="text-amber-500 font-normal ml-1"
            title={`This market's latest reported data is from ${staleYear} -- Comtrade hasn't published a newer year yet.`}
          >
            ({staleYear})
          </span>
        )}
        {lastKnown != null && (
          <span
            className="text-gray-400 font-normal ml-1 text-[10px]"
            title={`Afghanistan has no recorded exports here this year. Last known: ${formatUSD(lastKnown.value)} in ${lastKnown.year}.`}
          >
            (last {lastKnown.year}: {formatUSD(lastKnown.value)})
          </span>
        )}
      </span>
    </div>
  )
}

function MinScoreFilter({ current, hsCode }: { current?: number; hsCode: string }) {
  const options = [
    { label: 'All markets', value: undefined },
    { label: 'Score ≥ 40', value: 40 },
    { label: 'Score ≥ 60', value: 60 },
    { label: 'Score ≥ 70', value: 70 },
  ]
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-400">Filter:</span>
      {options.map((opt) => {
        const isActive = (opt.value ?? 0) === (current ?? 0)
        const href = opt.value ? `/discover/${hsCode}?min_score=${opt.value}` : `/discover/${hsCode}`
        return (
          <Link
            key={opt.label}
            href={href}
            className={`px-2.5 py-1 rounded-full border transition-colors ${
              isActive
                ? 'bg-[#0468B1] text-white border-[#0468B1]'
                : 'border-gray-300 text-gray-600 hover:border-[#0468B1] hover:text-[#0468B1]'
            }`}
          >
            {opt.label}
          </Link>
        )
      })}
    </div>
  )
}
