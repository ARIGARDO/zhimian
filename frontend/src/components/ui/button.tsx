import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const buttonVariants = cva('app-button', {
  variants: {
    variant: { default: 'app-button-primary', secondary: 'app-button-secondary', outline: 'app-button-outline', ghost: 'app-button-ghost' },
    size: { default: '', sm: 'app-button-sm' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
})

type Props = React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }
export function Button({ asChild = false, className, variant, size, ...props }: Props) {
  const Comp = asChild ? Slot : 'button'
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
