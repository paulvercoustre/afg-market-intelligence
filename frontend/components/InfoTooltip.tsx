'use client'

import { useState } from 'react'

export default function InfoTooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative inline-block ml-1 align-middle">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        aria-label="More info"
        aria-expanded={open}
        className="w-3.5 h-3.5 inline-flex items-center justify-center rounded-full border border-gray-300 text-gray-400 text-[9px] leading-none hover:border-[#0468B1] hover:text-[#0468B1] focus:outline-none focus:border-[#0468B1] focus:text-[#0468B1]"
      >
        i
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute z-10 left-1/2 -translate-x-1/2 bottom-full mb-1.5 w-48 rounded-md bg-gray-900 text-white text-[10px] leading-snug px-2.5 py-1.5 shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  )
}
