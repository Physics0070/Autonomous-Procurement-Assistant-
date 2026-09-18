import * as React from "react"
import { Bot, Plus, Send, Wrench } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Alert, Spinner } from "@/components/ui/feedback"
import { Textarea } from "@/components/ui/input"
import { useConversation, useConversations, useSendMessage, type ConversationMessage } from "@/hooks/automation"
import { ApiError } from "@/lib/api"
import { cn, relativeTime } from "@/lib/utils"

const EXAMPLES = [
  "Which open procurement requests have quotations waiting?",
  "Who is recommended for my latest request, and why?",
  "Summarise our spend by supplier and their on-time delivery.",
]

function ToolStep({ call, result }: { call: ConversationMessage["tool_calls"][number]; result?: ConversationMessage }) {
  return (
    <details className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none">
        <Wrench className="mr-1 inline h-3 w-3" />
        {call.name.replace(/_/g, " ")}
      </summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-muted-foreground">{JSON.stringify(call.arguments, null, 2)}</pre>
      {result?.content && <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap">{result.content}</pre>}
    </details>
  )
}

function Messages({ messages }: { messages: ConversationMessage[] }) {
  const results = new Map(messages.filter((m) => m.role === "tool").map((m) => [m.tool_call_id, m]))
  return (
    <div className="space-y-3">
      {messages.filter((m) => m.role === "user" || m.role === "assistant").map((m, i) => (
        <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
          <div className={cn("max-w-[85%] space-y-2 rounded-lg px-3.5 py-2.5 text-sm",
                             m.role === "user" ? "bg-primary text-primary-foreground" : "bg-card border")}>
            {m.tool_calls.map((call) => <ToolStep key={call.id} call={call} result={results.get(call.id)} />)}
            {m.content && <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>}
          </div>
        </div>
      ))}
    </div>
  )
}

export function AssistantPage() {
  const [conversationId, setConversationId] = React.useState<string | null>(null)
  const [draft, setDraft] = React.useState("")
  const [pending, setPending] = React.useState<string | null>(null)
  const conversations = useConversations()
  const conversation = useConversation(conversationId)
  const send = useSendMessage()
  const bottom = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" })
  }, [conversation.data, pending])

  async function submit(text: string) {
    if (!text.trim() || send.isPending) return
    setPending(text)
    setDraft("")
    try {
      const reply = await send.mutateAsync({ message: text, conversation_id: conversationId })
      setConversationId(reply.conversation_id)
    } finally {
      setPending(null)
    }
  }

  const notConfigured = send.error instanceof ApiError && send.error.status === 503

  return (
    <div>
      <PageHeader title="Assistant" description="Ask about your requests, quotations, suppliers and spend. Answers come from your own records; drafts it prepares still need your approval." />
      <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <Card className="h-fit p-2">
          <Button variant="ghost" className="w-full justify-start" onClick={() => setConversationId(null)}>
            <Plus className="h-4 w-4" />New conversation
          </Button>
          <ul className="mt-1 space-y-0.5">
            {conversations.data?.map((c) => (
              <li key={c.id}>
                <button onClick={() => setConversationId(c.id)}
                        className={cn("w-full rounded-md px-3 py-2 text-left text-sm hover:bg-accent", conversationId === c.id && "bg-primary/10 text-primary")}>
                  <span className="line-clamp-1">{c.title}</span>
                  <span className="text-xs text-muted-foreground">{relativeTime(c.updated_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="flex min-h-[60vh] flex-col p-4">
          <div className="flex-1 space-y-3 overflow-y-auto">
            {!conversationId && !pending && (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <Bot className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Try one of these:</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((e) => <Button key={e} variant="outline" size="sm" onClick={() => submit(e)}>{e}</Button>)}
                </div>
              </div>
            )}
            {conversationId && conversation.data && <Messages messages={conversation.data.messages} />}
            {pending && (
              <>
                <Messages messages={[{ role: "user", content: pending, tool_calls: [], tool_call_id: null, name: null, at: "" }]} />
                <p className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />Looking through your records…</p>
              </>
            )}
            {send.error && (
              <Alert tone={notConfigured ? "warning" : "error"} title={notConfigured ? "The assistant needs an AI provider" : undefined}>
                {send.error.message}
              </Alert>
            )}
            <div ref={bottom} />
          </div>
          <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); void submit(draft) }}>
            <Textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask a question…"
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(draft) } }} />
            <Button type="submit" disabled={!draft.trim() || send.isPending} aria-label="Send"><Send className="h-4 w-4" /></Button>
          </form>
        </Card>
      </div>
    </div>
  )
}
