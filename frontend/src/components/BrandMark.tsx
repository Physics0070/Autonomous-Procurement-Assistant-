import * as React from "react"

/** Each instance needs its own gradient id: a gradient defined inside a hidden (display:none) SVG does not resolve. */
export function BrandMark({ className }: { className?: string }) {
  const id = `bm-${React.useId().replace(/:/g, "")}`
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="hsl(var(--glow))" />
          <stop offset="1" stopColor="hsl(var(--glow-2))" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill="hsl(var(--background))" />
      <rect width="64" height="64" rx="18" fill="none" stroke={`url(#${id})`} strokeOpacity=".55" />
      <path d="M19 45V19h17a9.5 9.5 0 010 19H27" fill="none" stroke={`url(#${id})`} strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
