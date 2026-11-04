import type { FormField } from './types'

export function requiredFieldError(
  fields: Record<string, FormField>,
  values: Record<string, unknown>,
): string | null {
  for (const [key, config] of Object.entries(fields)) {
    if (!config.required) continue
    const value = values[key]
    if (value == null || value === '') return `${config.label} is required`
  }
  return null
}

export function payloadFromValues(
  fields: Record<string, FormField>,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const [key, config] of Object.entries(fields)) {
    if (config.readonly) continue
    if (key in values) payload[key] = values[key]
    if (config.type === 'boolean' && payload[key] == null) payload[key] = false
  }
  return payload
}

function isEmpty(value: unknown): boolean {
  return value == null || value === ''
}

export function valuesEqual(a: unknown, b: unknown, type?: string): boolean {
  if (isEmpty(a) && isEmpty(b)) return true
  if (type === 'boolean') return Boolean(a) === Boolean(b)
  if (type === 'date') return String(a ?? '').slice(0, 10) === String(b ?? '').slice(0, 10)
  if (type === 'number' || type === 'integer') {
    if (isEmpty(a) && isEmpty(b)) return true
    return Number(a) === Number(b)
  }
  return String(a ?? '') === String(b ?? '')
}

export function formatFieldValue(value: unknown, type?: string, labels?: Record<string, string>): string {
  if (isEmpty(value)) return '—'
  if (type === 'boolean') return value ? 'Yes' : 'No'
  if (type === 'date') return String(value).slice(0, 10)
  return labels?.[String(value)] ?? String(value)
}

export type FieldChange = {
  key: string
  label: string
  from: unknown
  to: unknown
  type?: string
  lookup: boolean
  labels?: Record<string, string>
}

export type FieldPreview = {
  key: string
  label: string
  value: unknown
  type?: string
  lookup: boolean
  labels?: Record<string, string>
}

export function fieldPreview(
  fields: Record<string, FormField>,
  values: Record<string, unknown>,
): FieldPreview[] {
  return Object.entries(fields)
    .filter(([, config]) => !config.readonly)
    .map(([key, config]) => ({
    key,
    label: config.label,
    value: values[key],
    type: config.type,
    lookup: Boolean(config.source_table),
    labels: config.option_labels,
  }))
}

export function fieldChanges(
  fields: Record<string, FormField>,
  original: Record<string, unknown>,
  next: Record<string, unknown>,
): FieldChange[] {
  const changes: FieldChange[] = []
  for (const [key, config] of Object.entries(fields)) {
    if (config.readonly) continue
    if (valuesEqual(original[key], next[key], config.type)) continue
    changes.push({
      key,
      label: config.label,
      from: original[key],
      to: next[key],
      type: config.type,
      lookup: Boolean(config.source_table),
      labels: config.option_labels,
    })
  }
  return changes
}
