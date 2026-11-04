import { createPortal } from 'react-dom'
import { CallScreen } from './CallScreen'
import { useCallEngine } from './useCallEngine'

/**
 * Where calls live: one per signed-in page, outside any screen, so a call goes on while people move around Orion. It is a separate
 * download (the shell loads it after start-up), because most visits never use it.
 */
export default function CallHost() {
  const engine = useCallEngine()
  if (engine.view.phase === 'idle') return null
  return createPortal(<CallScreen engine={engine} />, document.body)
}
