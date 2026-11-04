import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

/**
 * Keeps a render error contained to one region. Without this a single bad chart
 * prop unmounts the whole app and leaves a blank page with nothing on screen to
 * explain why, so the message is shown rather than swallowed.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; label?: string },
  { message: string | null }
> {
  state = { message: null as string | null }

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Render failed', error, info.componentStack)
  }

  render() {
    if (this.state.message === null) return this.props.children

    return (
      <div className="rounded-xl border border-warning/30 bg-warning-dim p-4">
        <p className="flex items-center gap-2 text-sm font-medium text-warning">
          <AlertTriangle className="h-4 w-4" />
          {this.props.label ?? 'This section could not be displayed.'}
        </p>
        <p className="mt-1 pl-6 text-xs text-[color:var(--color-text)]">{this.state.message}</p>
        <p className="mt-1 pl-6 text-xs text-[color:var(--color-text-muted)]">
          The browser console has the full component stack.
        </p>
      </div>
    )
  }
}
