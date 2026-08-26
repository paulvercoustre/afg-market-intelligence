export function formatUSD(value: number | null | undefined, compact = true): string {
  if (value == null) return '—'
  if (compact) {
    if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
    if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
    if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(0)}K`
    return `$${value.toFixed(0)}`
  }
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

export function formatPct(
  value: number | null | undefined,
  decimals = 1,
  showSign = true,
): string {
  if (value == null) return '—'
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

export function formatScore(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toFixed(1)
}

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return 'text-gray-400'
  if (score >= 70) return 'text-green-600'
  if (score >= 40) return 'text-amber-600'
  return 'text-red-500'
}

export function scoreBg(score: number | null | undefined): string {
  if (score == null) return 'bg-gray-100 text-gray-500'
  if (score >= 70) return 'bg-green-100 text-green-800'
  if (score >= 40) return 'bg-amber-100 text-amber-800'
  return 'bg-red-100 text-red-700'
}

export function scoreBarColor(score: number | null | undefined): string {
  if (score == null) return 'bg-gray-300'
  if (score >= 70) return 'bg-green-500'
  if (score >= 40) return 'bg-amber-400'
  return 'bg-red-400'
}

export function rankOrdinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}
