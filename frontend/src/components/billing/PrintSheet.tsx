import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { BillView, SavedBill } from '../../types'
import { BillDocument } from './BillDocument'

/** Draws the bill outside the app shell. The print stylesheet hides everything else. */
export function PrintSheet({ bill }: { bill: BillView }) {
  const [host] = useState(() => {
    const element = document.createElement('div')
    element.className = 'bill-print-root'
    return element
  })

  useEffect(() => {
    document.body.appendChild(host)
    return () => {
      host.remove()
    }
  }, [host])

  return createPortal(<BillDocument bill={bill} />, host)
}

/** The browser's print dialog, with the bill number as the file name when saving as PDF. */
export function printBill(fileTitle: string) {
  const previous = document.title
  document.title = fileTitle
  const restore = () => {
    document.title = previous
    window.removeEventListener('afterprint', restore)
  }
  window.addEventListener('afterprint', restore)
  window.print()
}

export function savedToView(bill: SavedBill): BillView {
  return { ...bill, number: bill.bill_number }
}
