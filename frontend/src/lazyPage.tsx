import { Component, lazy, Suspense, type ComponentType, type ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { LoadingState } from './components/ui/DataTable'

/**
 * A page that is fetched the first time someone opens it, not with the app. Each page is its own boundary, so the screen around it
 * (a workspace's tabs, the navigation rail) stays where it is while the page arrives, and a page that cannot be fetched says so
 * where it would have been.
 *
 *     const BillingPage = lazyPage(() => import('./pages/utility/BillingPage'), 'BillingPage')
 */
export function lazyPage<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K): ComponentType {
  const Page = lazy<ComponentType>(() => load().then((module) => ({ default: module[name] as ComponentType })))
  function LazyPage() {
    return (
      <ChunkBoundary>
        <Suspense fallback={<LoadingState message="Loading…" />}>
          <Page />
        </Suspense>
      </ChunkBoundary>
    )
  }
  LazyPage.displayName = `Lazy(${name})`
  return LazyPage
}

/** The browsers' different words for "the file this page needs is not there". */
export function isChunkLoadError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error)
  return /dynamically imported module|importing a module script failed|loading chunk|ChunkLoadError/i.test(text)
}

/**
 * After a new version is released the old page's files are gone from the server, so a tab left open since before the release
 * cannot fetch a page it has not opened yet. That is not a fault in the page: the tab is simply out of date. Anything else
 * that goes wrong is passed up to whatever boundary is above, as before.
 */
export class ChunkBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  render() {
    const { error } = this.state
    if (error === null) return this.props.children
    if (!isChunkLoadError(error)) throw error
    return (
      <div className="mx-auto max-w-md rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-center">
        <p className="t-h3">Orion was updated</p>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          This page belongs to a newer version than the one open in this tab. Reload to continue; anything you have already saved is safe.
        </p>
        <button type="button" onClick={() => window.location.reload()} className="btn-primary interactive mt-4 inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Reload
        </button>
      </div>
    )
  }
}
