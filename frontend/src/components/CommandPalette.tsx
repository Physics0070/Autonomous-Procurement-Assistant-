import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { Search, CornerDownLeft } from "lucide-react"
import { cn } from "@/lib/utils"

export type Command = { id: string; label: string; hint?: string; icon: React.ComponentType<{ className?: string }>; run: () => void }

/** Ctrl/Cmd+K: jump to any page or run an action. Arrow keys move, Enter runs, Escape closes. */
export function CommandPalette({ commands, open, onOpenChange }: { commands: Command[]; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [query, setQuery] = React.useState("")
  const [active, setActive] = React.useState(0)
  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? commands.filter((c) => `${c.label} ${c.hint ?? ""}`.toLowerCase().includes(q)) : commands
  }, [commands, query])

  React.useEffect(() => { setActive(0) }, [query, open])
  React.useEffect(() => { if (!open) setQuery("") }, [open])

  const run = (command?: Command) => { if (!command) return; onOpenChange(false); command.run() }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-md data-[state=open]:animate-fade-in" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="glass fixed left-1/2 top-[18%] z-[71] w-[min(92vw,34rem)] -translate-x-1/2 overflow-hidden rounded-2xl border bg-card/90 shadow-[0_40px_120px_-20px_hsl(228_60%_2%/0.9)] data-[state=open]:animate-rise"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
            if (e.key === "Enter") { e.preventDefault(); run(results[active]) }
          }}
        >
          <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
          <div className="flex items-center gap-3 border-b px-4">
            <Search className="h-4 w-4 text-primary" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Jump to a page or run an action…"
              className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground"
              aria-label="Search commands"
            />
            <span className="kbd">esc</span>
          </div>
          <ul className="max-h-[22rem] overflow-y-auto p-2 scrollbar-thin" role="listbox">
            {results.length === 0 && <li className="px-3 py-8 text-center text-sm text-muted-foreground">Nothing matches “{query}”.</li>}
            {results.map((command, index) => (
              <li key={command.id} role="option" aria-selected={index === active}>
                <button
                  onMouseMove={() => setActive(index)}
                  onClick={() => run(command)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                    index === active ? "bg-primary/15 text-foreground shadow-[0_0_0_1px_hsl(var(--primary)/0.35)_inset]" : "text-muted-foreground",
                  )}
                >
                  <command.icon className={cn("h-4 w-4", index === active && "text-primary")} />
                  <span className="flex-1 font-medium">{command.label}</span>
                  {command.hint && <span className="text-xs text-muted-foreground">{command.hint}</span>}
                  {index === active && <CornerDownLeft className="h-3.5 w-3.5 text-primary" />}
                </button>
              </li>
            ))}
          </ul>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
