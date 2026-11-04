import { useEffect, useState } from 'react'

/** True when the viewport matches a small-screen media query. */
export function useNarrow(query = '(max-width: 639px)'): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  )

  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = () => setMatches(media.matches)
    onChange()
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])

  return matches
}

export function useChartMotion() {
  const reduce = useNarrow('(prefers-reduced-motion: reduce)')
  return {
    isAnimationActive: !reduce,
    animationDuration: 520,
  }
}
