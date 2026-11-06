import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/btn relative inline-flex items-center justify-center gap-2 overflow-hidden whitespace-nowrap rounded-lg text-sm font-medium transition-all duration-200 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-gradient-to-b from-primary to-[hsl(var(--glow-2)/0.92)] text-primary-foreground shadow-[0_8px_24px_-8px_hsl(var(--glow)/0.8),0_1px_0_hsl(0_0%_100%/0.35)_inset] hover:-translate-y-0.5 hover:shadow-[0_14px_30px_-8px_hsl(var(--glow)/0.9),0_1px_0_hsl(0_0%_100%/0.35)_inset] before:absolute before:inset-y-0 before:left-0 before:w-1/3 before:-translate-x-[120%] before:bg-white/40 before:blur-md before:content-[''] hover:before:animate-[sweep_0.9s_ease-out]",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline: "border border-input bg-card/40 backdrop-blur hover:border-primary/60 hover:bg-primary/10 hover:text-foreground hover:shadow-[0_0_0_1px_hsl(var(--primary)/0.3),0_8px_24px_-12px_hsl(var(--glow)/0.6)]",
        secondary: "bg-secondary/80 text-secondary-foreground backdrop-blur hover:bg-accent",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-lg px-3 text-xs",
        lg: "h-11 rounded-xl px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  },
)
Button.displayName = "Button"

export { Button, buttonVariants }
