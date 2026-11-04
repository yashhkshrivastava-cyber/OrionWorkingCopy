import type { ReactNode } from 'react'
import type { User } from '../../types'
import { LumenDock } from './LumenDock'
import { LumenLauncher } from './LumenLauncher'
import { LumenMobileBar } from './LumenMobileBar'
import { LumenTopBar } from './LumenTopBar'

/**
 * Everything that frames the page in the Lumen interface: the dock, the top bar, the phone bar and the launcher, around the page itself (`children`).
 * It is loaded only when someone uses Lumen, so the classic interface does not pay for it in its start-up download.
 */
export default function LumenFrame({
  user,
  unread,
  dockOpen,
  onDockOpen,
  launcherOpen,
  setLauncherOpen,
  onRaiseRequest,
  children,
  overlays,
}: {
  user: User
  unread: number
  dockOpen: boolean
  onDockOpen: (value: boolean) => void
  launcherOpen: boolean
  setLauncherOpen: (value: boolean) => void
  onRaiseRequest: () => void
  children: ReactNode
  overlays: ReactNode
}) {
  return (
    <div className="app-canvas lumen-canvas flex h-dvh overflow-hidden">
      <LumenDock user={user} unread={unread} open={dockOpen} onOpen={onDockOpen} onLauncher={() => setLauncherOpen(true)} onRaiseRequest={onRaiseRequest} />
      <div className="lumen-main flex min-w-0 flex-1 flex-col" data-open={dockOpen}>
        <LumenTopBar user={user} onRaiseRequest={onRaiseRequest} />
        {children}
      </div>
      <LumenMobileBar unread={unread} onLauncher={() => setLauncherOpen(true)} />
      <LumenLauncher open={launcherOpen} user={user} unread={unread} onClose={() => setLauncherOpen(false)} />
      {overlays}
    </div>
  )
}
