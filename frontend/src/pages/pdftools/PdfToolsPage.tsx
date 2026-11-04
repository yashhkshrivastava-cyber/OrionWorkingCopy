import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { api } from '../../api/client'
import type { PdfToolLimits } from '../../types'

/** What the screens of the PDF tools share: the limits the server sets, and a file passed on from one tool to the next. */
export interface PdfToolsContext {
  limits: PdfToolLimits | null
  /** A file passed on to a tool: only that tool takes it (the screen being left may still be drawn for a moment). */
  carry: Carried | null
  setCarry: (carried: Carried | null) => void
}

export interface Carried {
  tool: string
  files: File[]
}

/** The PDF tools: merge, split, rotate, compress, lock and the rest. Every file is processed in memory on the server and then forgotten. */
export function PdfToolsPage() {
  const [limits, setLimits] = useState<PdfToolLimits | null>(null)
  const [carry, setCarry] = useState<Carried | null>(null)

  useEffect(() => {
    let live = true
    api
      .pdfToolLimits()
      .then((found) => live && setLimits(found))
      .catch(() => undefined) // the screens fall back to the usual limits, and the server checks them again
    return () => {
      live = false
    }
  }, [])

  return (
    <div className="w-full">
      <Outlet context={{ limits, carry, setCarry } satisfies PdfToolsContext} />
    </div>
  )
}
