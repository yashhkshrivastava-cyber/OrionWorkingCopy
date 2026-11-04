/**
 * The address of a form in Operational Data opened from a client's, case's or employee's page: which record type, whether to add or change, which record, what to fill in
 * and where "back" goes. The data page reads it (`OperationalDataPage`), behind the usual change warning, and checks every field name against the record type.
 */
export function formLink({
  entity,
  mode,
  record,
  fill,
  back,
  backLabel,
}: {
  entity: string
  mode: 'create' | 'edit'
  /** The code of the record to change (mode edit). */
  record?: string
  /** Fields to start an Add form with, by field name. */
  fill?: Record<string, string | null | undefined>
  /** The page to return to, and what to call it. */
  back?: string
  backLabel?: string
}): string {
  const query = new URLSearchParams({ intent: 'change', entity, mode })
  if (record) query.set('record', record)
  for (const [field, value] of Object.entries(fill ?? {})) if (value) query.append('fill', `${field}:${value}`)
  if (back) {
    query.set('return', back)
    if (backLabel) query.set('returnLabel', backLabel)
  }
  return `/data/operational?${query.toString()}`
}
