import { splitBillNumbers } from '../../billing/billLink'
import { BillNumber } from '../billing/BillNumber'

/** Text that may mention bills ("GST paid on bill 2026-27/202"): each number is the link with the card, the rest is plain. */
export function BillText({ text }: { text: string | null | undefined }) {
  if (!text) return <>—</>
  return (
    <>
      {splitBillNumbers(text).map((piece, at) => (piece.bill ? <BillNumber key={at} number={piece.text} /> : piece.text))}
    </>
  )
}
