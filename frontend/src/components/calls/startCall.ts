/** Asks the call host to ring this conversation's other person. Anything on a page can do it; the host decides if a call can start now. */
export function startCall(chatId: number, kind: 'voice' | 'video') {
  window.dispatchEvent(new CustomEvent('orion-call-start', { detail: { chatId, kind } }))
}
