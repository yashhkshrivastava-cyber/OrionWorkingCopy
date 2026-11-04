import { useEffect } from 'react'

/**
 * While the Lumen interface is on, a soft light follows the pointer across whatever card it is over. One listener for the whole page writes the
 * pointer's place into two variables on the card under it (`--mx`, `--my`), and the stylesheet paints the light from them. Nothing re-renders.
 */
export function useLumenPointer(active: boolean) {
  useEffect(() => {
    if (!active || window.matchMedia?.('(pointer: coarse)').matches) return
    let frame = 0
    let last: HTMLElement | null = null
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const card = (event.target as Element | null)?.closest?.('.panel') as HTMLElement | null
        if (last && last !== card) {
          last.style.removeProperty('--mx')
          last.style.removeProperty('--my')
        }
        last = card
        if (!card) return
        const box = card.getBoundingClientRect()
        card.style.setProperty('--mx', `${event.clientX - box.left}px`)
        card.style.setProperty('--my', `${event.clientY - box.top}px`)
      })
    }
    document.addEventListener('pointermove', onMove, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('pointermove', onMove)
    }
  }, [active])
}
