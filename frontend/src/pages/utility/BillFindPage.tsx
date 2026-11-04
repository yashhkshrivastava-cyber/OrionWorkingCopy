import { useEffect, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { billPath } from '../../billing/billLink'
import { fetchBillCard } from '../../billing/useBillCard'
import { Alert } from '../../components/ui/Alert'
import { LoadingState } from '../../components/ui/DataTable'

/**
 * Where a bill number that is only a number lands (a dashboard table, an answer from the Copilot): it finds the bill the number is
 * printed on and shows it. It is its own address so that the number can be opened in a new tab before anything has been looked up.
 */
export function BillFindPage() {
  const [search] = useSearchParams()
  const number = (search.get('number') ?? '').trim()
  const [found, setFound] = useState<{ number: string; code: string | null; error?: string } | null>(null)

  useEffect(() => {
    if (!number) return
    let current = true
    fetchBillCard({ number })
      .then((card) => current && setFound({ number, code: card?.id ?? null }))
      .catch((error: Error) => current && setFound({ number, code: null, error: error.message }))
    return () => {
      current = false
    }
  }, [number])

  if (!number) return <Alert variant="error">No bill number was given.</Alert>
  if (!found || found.number !== number) return <LoadingState message={`Finding bill ${number}…`} />
  if (found.code) return <Navigate to={billPath(found.code)} replace />
  return (
    <div className="space-y-3">
      <Alert variant="error">{found.error ?? `There is no bill ${number}.`}</Alert>
      <Link to="/utility/billing" className="text-sm font-medium text-accent hover:underline">
        Back to bills
      </Link>
    </div>
  )
}
