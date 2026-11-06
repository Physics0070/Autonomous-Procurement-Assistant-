import * as React from "react"

/**
 * The signature moment: suppliers drift around a hub, and packets of data (quotations) travel
 * to it and make it pulse. The cursor lights up nearby nodes and pulls them gently.
 * Canvas 2D, one rAF loop, paused while off screen or the tab is hidden, a still frame under
 * reduced motion. Colours come from the theme tokens, so it follows light/dark.
 */
type Node = { x: number; y: number; ax: number; ay: number; r: number; phase: number; speed: number; glow: number }
type Packet = { from: number; t: number; speed: number }

const hsl = (token: string, alpha: number) => {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim()
  return `hsl(${raw || "40 100% 58%"} / ${alpha})`
}

export function SupplyNetwork({
  className,
  nodes: nodeCount = 26,
  hubPulse = 1,
}: {
  className?: string
  nodes?: number
  /** Packets per second: pass the number of quotations in flight to make the network busier. */
  hubPulse?: number
}) {
  const ref = React.useRef<HTMLCanvasElement>(null)
  const pulseRef = React.useRef(hubPulse)
  pulseRef.current = hubPulse

  React.useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let w = 0, h = 0, raf = 0, visible = true, last = performance.now(), spawn = 0, hubGlow = 0
    const pointer = { x: -999, y: -999 }
    let colors = { a: "", b: "", c: "", a2: "", fg: "" }
    const refreshColors = () => {
      colors = { a: hsl("--glow", 1), a2: hsl("--glow", 0.18), b: hsl("--aurora-b", 1), c: hsl("--glow-2", 1), fg: hsl("--foreground", 0.5) }
    }
    refreshColors()

    const nodes: Node[] = []
    const packets: Packet[] = []
    const seed = () => {
      nodes.length = 0
      for (let i = 0; i < nodeCount; i++) {
        const angle = (i / nodeCount) * Math.PI * 2 + Math.random() * 0.5
        const ring = 0.28 + Math.random() * 0.62
        nodes.push({ x: 0, y: 0, ax: Math.cos(angle) * ring, ay: Math.sin(angle) * ring * 0.78, r: 1.6 + Math.random() * 2.6, phase: Math.random() * 6.28, speed: 0.15 + Math.random() * 0.35, glow: 0 })
      }
    }
    const resize = () => {
      const box = canvas.getBoundingClientRect()
      w = box.width; h = box.height
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      seed()
    }
    const hub = () => ({ x: w * 0.62, y: h * 0.5 })

    const place = (now: number) => {
      const c = hub()
      const scale = Math.min(w, h * 1.5) * 0.62
      for (const n of nodes) {
        const t = now / 1000
        n.x = c.x + n.ax * scale + Math.sin(t * n.speed + n.phase) * 14
        n.y = c.y + n.ay * scale + Math.cos(t * n.speed * 0.8 + n.phase) * 12
        const dx = pointer.x - n.x, dy = pointer.y - n.y, d = Math.hypot(dx, dy)
        const near = Math.max(0, 1 - d / 190)
        n.glow += (near - n.glow) * 0.12
        if (near > 0) { n.x += dx * near * 0.06; n.y += dy * near * 0.06 }
      }
    }

    const curve = (n: Node, c: { x: number; y: number }) => {
      const mx = (n.x + c.x) / 2, my = (n.y + c.y) / 2
      const nx = -(c.y - n.y), ny = c.x - n.x, len = Math.hypot(nx, ny) || 1
      return { cx: mx + (nx / len) * len * 0.12, cy: my + (ny / len) * len * 0.12 }
    }
    const at = (n: Node, c: { x: number; y: number }, t: number) => {
      const { cx, cy } = curve(n, c)
      const u = 1 - t
      return { x: u * u * n.x + 2 * u * t * cx + t * t * c.x, y: u * u * n.y + 2 * u * t * cy + t * t * c.y }
    }

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now
      ctx.clearRect(0, 0, w, h)
      place(now)
      const c = hub()

      // links to the hub, brighter near the cursor
      for (const n of nodes) {
        const { cx, cy } = curve(n, c)
        ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.quadraticCurveTo(cx, cy, c.x, c.y)
        ctx.strokeStyle = n.glow > 0.05 ? hsl("--glow", 0.12 + n.glow * 0.55) : colors.a2
        ctx.lineWidth = 0.6 + n.glow * 1.4
        ctx.stroke()
      }
      // nodes
      for (const n of nodes) {
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + n.glow * 3, 0, Math.PI * 2)
        ctx.fillStyle = n.glow > 0.2 ? colors.a : colors.fg
        ctx.shadowColor = n.glow > 0.2 ? colors.a : "transparent"; ctx.shadowBlur = n.glow * 16
        ctx.fill(); ctx.shadowBlur = 0
      }
      // packets
      spawn += dt * (0.9 + pulseRef.current * 0.6)
      if (spawn > 0.55 && packets.length < 18 && !reduced) { spawn = 0; packets.push({ from: (Math.random() * nodes.length) | 0, t: 0, speed: 0.38 + Math.random() * 0.4 }) }
      for (let i = packets.length - 1; i >= 0; i--) {
        const p = packets[i]; p.t += dt * p.speed
        if (p.t >= 1) { hubGlow = 1; packets.splice(i, 1); continue }
        const pos = at(nodes[p.from], c, p.t)
        const tail = at(nodes[p.from], c, Math.max(0, p.t - 0.09))
        const g = ctx.createLinearGradient(tail.x, tail.y, pos.x, pos.y)
        g.addColorStop(0, "transparent"); g.addColorStop(1, p.from % 3 === 0 ? colors.b : colors.c)
        ctx.strokeStyle = g; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(tail.x, tail.y); ctx.lineTo(pos.x, pos.y); ctx.stroke()
        ctx.beginPath(); ctx.arc(pos.x, pos.y, 2.2, 0, Math.PI * 2); ctx.fillStyle = p.from % 3 === 0 ? colors.b : colors.a; ctx.fill()
      }
      // hub: rings that expand when a packet lands
      hubGlow = Math.max(0, hubGlow - dt * 1.6)
      const base = Math.min(w, h) * 0.07
      for (let k = 0; k < 3; k++) {
        const ph = ((now / 2600 + k / 3) % 1)
        ctx.beginPath(); ctx.arc(c.x, c.y, base + ph * base * 3.2, 0, Math.PI * 2)
        ctx.strokeStyle = hsl("--glow", (1 - ph) * 0.22 + hubGlow * 0.15); ctx.lineWidth = 1; ctx.stroke()
      }
      const core = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, base * (1.6 + hubGlow * 0.5))
      core.addColorStop(0, colors.a); core.addColorStop(0.45, hsl("--glow-2", 0.55)); core.addColorStop(1, "transparent")
      ctx.fillStyle = core; ctx.beginPath(); ctx.arc(c.x, c.y, base * (1.6 + hubGlow * 0.5), 0, Math.PI * 2); ctx.fill()
      ctx.beginPath(); ctx.arc(c.x, c.y, base * 0.34, 0, Math.PI * 2); ctx.fillStyle = hsl("--background", 1); ctx.fill()
      ctx.lineWidth = 2; ctx.strokeStyle = colors.a; ctx.stroke()
    }

    const loop = (now: number) => { if (visible && !document.hidden) draw(now); raf = requestAnimationFrame(loop) }
    const onMove = (e: PointerEvent) => { const b = canvas.getBoundingClientRect(); pointer.x = e.clientX - b.left; pointer.y = e.clientY - b.top }
    const onLeave = () => { pointer.x = pointer.y = -999 }
    const observer = new ResizeObserver(resize); observer.observe(canvas)
    const io = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting }); io.observe(canvas)
    const theme = new MutationObserver(refreshColors); theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
    canvas.addEventListener("pointermove", onMove); canvas.addEventListener("pointerleave", onLeave)
    resize()
    if (reduced) draw(performance.now()); else raf = requestAnimationFrame(loop)
    return () => {
      cancelAnimationFrame(raf); observer.disconnect(); io.disconnect(); theme.disconnect()
      canvas.removeEventListener("pointermove", onMove); canvas.removeEventListener("pointerleave", onLeave)
    }
  }, [nodeCount])

  return <canvas ref={ref} className={className} aria-hidden role="presentation" />
}
