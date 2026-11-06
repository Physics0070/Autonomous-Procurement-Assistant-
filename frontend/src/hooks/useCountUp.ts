import * as React from "react"

/** Eases a number up from 0 once, so KPI figures land instead of just appearing. Instant under reduced motion. */
export function useCountUp(target: number, durationMs = 1100): number {
  const [value, setValue] = React.useState(0)
  React.useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !Number.isFinite(target)) {
      setValue(target)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs)
      setValue(target * (1 - Math.pow(1 - t, 4)))   // ease-out quart
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, durationMs])
  return value
}
