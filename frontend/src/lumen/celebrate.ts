/** A small burst of confetti where something was just finished. Only in the Lumen interface, and never for people who asked for less motion. */
export function celebrate(origin?: Element | { x: number; y: number } | null) {
  const root = document.documentElement
  if (root.dataset.experience !== 'lumen' || root.dataset.motion === 'reduced') return
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  let x = window.innerWidth / 2
  let y = window.innerHeight / 3
  if (origin && 'getBoundingClientRect' in origin) {
    const box = origin.getBoundingClientRect()
    x = box.left + box.width / 2
    y = box.top + box.height / 2
  } else if (origin) {
    x = origin.x
    y = origin.y
  }
  const colours = ['--orion-primary', '--orion-violet', '--orion-amber', '--orion-emerald', '--orion-rose']
  const pieces: HTMLElement[] = []
  for (let i = 0; i < 26; i++) {
    const piece = document.createElement('span')
    piece.className = 'lumen-confetti'
    const angle = Math.random() * Math.PI * 2
    const distance = 70 + Math.random() * 120
    piece.style.left = `${x}px`
    piece.style.top = `${y}px`
    piece.style.background = `var(${colours[i % colours.length]})`
    piece.style.setProperty('--dx', `${Math.cos(angle) * distance}px`)
    piece.style.setProperty('--dy', `${Math.sin(angle) * distance - 40}px`)
    piece.style.setProperty('--rot', `${Math.round(Math.random() * 540 - 270)}deg`)
    document.body.appendChild(piece)
    pieces.push(piece)
  }
  window.setTimeout(() => pieces.forEach((piece) => piece.remove()), 1300)
}
