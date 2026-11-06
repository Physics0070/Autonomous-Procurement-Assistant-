/** The mark: a "P" on a card-coloured tile, in the app's blue. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="hsl(var(--card))" stroke="hsl(var(--border))" />
      <path d="M19 46V18h16a10 10 0 010 20H27" fill="none" stroke="hsl(var(--primary))" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
