import { scoreBarColor, scoreColor } from '@/lib/utils'

interface ScoreBarProps {
  label: string
  score: number | null | undefined
  weight?: number
  // Overrides the displayed number (e.g. a raw "12.0%" tariff rate instead
  // of the abstract 0-100 score) while the bar's fill width/color still
  // follow `score` -- score is always oriented "higher is better" (for
  // tariff, a low rate produces a high score), so reusing it keeps this
  // bar visually comparable to the other dimensions on the same 0-100
  // scale, and keeps the color correctly "low tariff = green" without a
  // separate, inverted color rule.
  displayValue?: string
}

export default function ScoreBar({ label, score, weight, displayValue }: ScoreBarProps) {
  const pct = score != null ? Math.max(0, Math.min(100, score)) : 0
  const barColor = scoreBarColor(score)
  const hasData = score != null

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-36 text-gray-600 truncate shrink-0">{label}</span>
      <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
        {hasData && (
          <div
            className={`h-full rounded-full ${barColor} transition-all duration-500`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <span className={`w-12 text-right tabular-nums ${displayValue && hasData ? scoreColor(score) : 'text-gray-500'}`}>
        {hasData ? (displayValue ?? Math.round(pct)) : '—'}
      </span>
      {weight != null && (
        <span className="w-8 text-right text-gray-400 shrink-0">{(weight * 100).toFixed(0)}%</span>
      )}
    </div>
  )
}
