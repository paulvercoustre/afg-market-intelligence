'use client'

import { useState } from 'react'
import Link from 'next/link'
import type { ProductSummary } from '@/lib/types'
import { formatUSD } from '@/lib/utils'

const ALL = 'All'

export default function ProductGrid({ products }: { products: ProductSummary[] }) {
  const categories = [ALL, ...Array.from(new Set(products.map((p) => p.category))).sort()]
  const [query, setQuery] = useState('')
  const [activeCategory, setActiveCategory] = useState(ALL)

  const filtered = products.filter((p) => {
    const matchesCategory = activeCategory === ALL || p.category === activeCategory
    const matchesQuery =
      !query ||
      p.name.toLowerCase().includes(query.toLowerCase()) ||
      p.hs_codes.some((c) => c.includes(query))
    return matchesCategory && matchesQuery
  })

  return (
    <div>
      {/* Search + category filter */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="search"
          placeholder="Search by product name or HS code…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#0468B1] bg-white"
        />
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              activeCategory === cat
                ? 'bg-[#0468B1] text-white'
                : 'bg-white text-gray-600 border border-gray-300 hover:border-[#0468B1] hover:text-[#0468B1]'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {filtered.length === 0 && (
        <p className="text-gray-500 text-sm py-12 text-center">No products match your search.</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((product) => (
          <ProductCard key={product.id} product={product} />
        ))}
      </div>
    </div>
  )
}

function ProductCard({ product }: { product: ProductSummary }) {
  const primaryHsCode = product.hs_codes[0]

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col hover:shadow-md hover:border-[#0468B1]/40 transition-all">
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#0468B1] bg-[#E8F2FA] px-2 py-0.5 rounded">
          {product.category}
        </span>
        {product.has_data ? (
          <span className="text-[10px] text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded">
            Data available
          </span>
        ) : (
          <span className="text-[10px] text-gray-400 bg-gray-50 border border-gray-200 px-2 py-0.5 rounded">
            No data yet
          </span>
        )}
      </div>

      <h3 className="font-semibold text-sm text-gray-900 mb-1 leading-snug">{product.name}</h3>
      <p className="text-xs text-gray-400 mb-3">HS {product.hs_codes.join(', ')}</p>

      {product.has_data && (
        <div className="text-xs text-gray-600 space-y-1 mb-4">
          {product.total_export_value_usd != null && (
            <div className="flex justify-between">
              <span className="text-gray-400">Afghan exports</span>
              <span className="font-medium">{formatUSD(product.total_export_value_usd)}</span>
            </div>
          )}
          {product.top_market_name && (
            <div className="flex justify-between">
              <span className="text-gray-400">Top market</span>
              <span className="font-medium truncate ml-2">{product.top_market_name}</span>
            </div>
          )}
          {product.last_year && (
            <div className="flex justify-between">
              <span className="text-gray-400">Year</span>
              <span className="font-medium">{product.last_year}</span>
            </div>
          )}
        </div>
      )}

      <div className="mt-auto">
        {product.has_data ? (
          <Link
            href={`/discover/${primaryHsCode}`}
            className="block w-full text-center text-xs font-semibold py-2 px-4 rounded-lg bg-[#0468B1] text-white hover:bg-[#035891] transition-colors"
          >
            Discover markets →
          </Link>
        ) : (
          <span className="block w-full text-center text-xs py-2 px-4 rounded-lg bg-gray-100 text-gray-400 cursor-not-allowed">
            No data available
          </span>
        )}
      </div>
    </div>
  )
}
