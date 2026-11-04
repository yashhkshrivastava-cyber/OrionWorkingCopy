import type { FormField } from '../types'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useDataRefresh } from '../context/DataRefreshContext'
import { Field, Input, Checkbox, Textarea } from './ui/Field'
import { MoneyInput } from './ui/MoneyInput'
import { SearchSelect, optionIdEquals } from './ui/SearchSelect'
import { AmountBreakdownBox } from './AmountBreakdownBox'
import { useLumen } from '../lumen/useLumen'
import { FormSection, SegmentedChoice, FormProgress, QuickDates } from '../lumen/formParts'

interface Props {
  entityName: string
  fields: Record<string, FormField>
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  /** When set (update), keep stored auto-generated fields until the user edits them. */
  hydrateKey?: string
  /** Fields that are fixed and cannot be changed here (the won opportunity a case is being made for), with why. */
  lockedFields?: Record<string, string>
  /** A lookup that offers only these choices instead of every record (an EMD's case: only the opportunity's cases). */
  optionOverrides?: Record<string, Option[]>
}

type Option = { id: string; label: string }

function toNumber(value: unknown): number {
  if (value == null || value === '') return 0
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100
}

function monthYearFrom(value: unknown): string | null {
  if (value == null || value === '') return null
  const text = String(value)
  if (text.length >= 7 && text[4] === '-') return text.slice(0, 7)
  return null
}

function computedValue(config: FormField, values: Record<string, unknown>): number | string | null {
  const keys = config.compute_from || []
  if (!keys.length) return null
  if (config.compute_op === 'month_year') return monthYearFrom(values[keys[0]])
  if (config.compute_op === 'difference') {
    if (keys.some((key) => values[key] == null || values[key] === '')) return null
    return roundMoney(toNumber(values[keys[0]]) - keys.slice(1).reduce((sum, key) => sum + toNumber(values[key]), 0))
  }
  return roundMoney(keys.reduce((sum, key) => sum + toNumber(values[key]), 0))
}

function formatAutoPart(key: string, value: unknown, options: Option[] = [], useLabel = false): string {
  if (value == null || value === '') return ''
  if (key.includes('date')) return String(value).slice(0, 10)
  if (typeof value === 'number' || key.includes('amount')) {
    const n = toNumber(value)
    return Number.isInteger(n) ? String(n) : String(roundMoney(n))
  }
  if (useLabel) {
    return options.find((option) => optionIdEquals(option.id, value))?.label || ''
  }
  return String(value)
}

function lookupLabelsFrom(values: Record<string, unknown>): Record<string, string> {
  const raw = values.__labels
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  return raw as Record<string, string>
}

export function EntityForm({ entityName, fields, values, onChange, hydrateKey = '', lockedFields, optionOverrides }: Props) {
  const { generation } = useDataRefresh()
  const [optionsCache, setOptionsCache] = useState<Record<string, Option[]>>({})
  const [states, setStates] = useState<string[]>([])
  const [cities, setCities] = useState<string[]>([])
  const [overridden, setOverridden] = useState<Record<string, boolean>>({})
  const [customMode, setCustomMode] = useState<Record<string, boolean>>({})
  const lookupLabels = lookupLabelsFrom(values)
  const lumen = useLumen()

  const entries = Object.entries(fields)
  const firstBreakdown = entries.findIndex(([, config]) => config.breakdown)
  const beforeFields = (firstBreakdown === -1 ? entries : entries.slice(0, firstBreakdown)).filter(
    ([, config]) => !config.breakdown,
  )
  const afterFields = (firstBreakdown === -1 ? [] : entries.slice(firstBreakdown)).filter(
    ([, config]) => !config.breakdown,
  )
  const hasBreakdown = firstBreakdown !== -1
  const amountField =
    entries.find(
      ([name, config]) =>
        config.breakdown && !['tax', 'gst', 'amount_after_tax_gst'].includes(name),
    )?.[0] || 'transaction_amount'

  useEffect(() => {
    setOverridden({})
    setOptionsCache({})
    setCustomMode({})
  }, [entityName, hydrateKey])

  const isLocked = (name: string, config: FormField) => {
    if (overridden[name] === true) return true
    if (overridden[name] === false) return false
    if (hydrateKey && config.auto_parts?.length && values[name] != null && values[name] !== '') return true
    return false
  }

  useEffect(() => {
    const needsStates = Object.values(fields).some((f) => f.type === 'state' || f.type === 'dependent_select')
    if (needsStates) api.states().then((r) => setStates(r.states))
  }, [fields])

  useEffect(() => {
    const stateField = Object.entries(fields).find(([, f]) => f.type === 'dependent_select')
    if (!stateField) return
    const [, config] = stateField
    const parent = config.depends_on
    if (!parent) return
    const stateVal = values[parent] as string
    if (stateVal) api.cities(stateVal).then((r) => setCities(r.cities))
    else setCities([])
  }, [fields, values])

  useEffect(() => {
    Object.entries(fields).forEach(([name, config]) => {
      if (!config.source_table) return
      api.fieldOptions(entityName, name).then((opts) => {
        setOptionsCache((cache) => ({ ...cache, [name]: opts }))
      })
    })
  }, [entityName, fields, generation])

  useEffect(() => {
    Object.entries(fields).forEach(([name, config]) => {
      if (!config.required || config.source_table || config.type !== 'select') return
      if (!config.options?.length) return
      if (values[name] == null || values[name] === '') onChange(name, config.options[0])
    })
  }, [entityName, fields, onChange, values])

  const sourceSnapshot = JSON.stringify(
    Object.fromEntries(
      Object.entries(fields).flatMap(([, config]) =>
        (config.compute_from || []).map((key) => [key, values[key]]),
      ),
    ),
  )

  useEffect(() => {
    Object.entries(fields).forEach(([name, config]) => {
      if (!config.compute_from?.length || isLocked(name, config)) return
      const next = computedValue(config, values)
      const current =
        values[name] == null || values[name] === ''
          ? null
          : typeof next === 'number'
            ? roundMoney(toNumber(values[name]))
            : String(values[name])
      if (current !== next) onChange(name, next)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- isLocked is a new function every render and reads overridden and values, which are listed
  }, [fields, onChange, overridden, sourceSnapshot, values])

  const autoSnapshot = JSON.stringify(
    Object.fromEntries(
      Object.entries(fields).flatMap(([, config]) =>
        (config.auto_parts || []).map((key) => [
          key,
          values[key],
          optionsCache[key]?.find((option) => optionIdEquals(option.id, values[key]))?.label,
        ]),
      ),
    ),
  )

  useEffect(() => {
    Object.entries(fields).forEach(([name, config]) => {
      if (!config.auto_parts?.length || isLocked(name, config)) return
      const parts = config.auto_parts.map((key) =>
        formatAutoPart(key, values[key], optionsCache[key] || [], Boolean(fields[key]?.source_table)),
      )
      if (parts.some((part) => !part)) return
      const next = parts.join('-')
      if (String(values[name] ?? '') !== next) onChange(name, next)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- isLocked is a new function every render and reads overridden and values, which are listed
  }, [autoSnapshot, fields, onChange, optionsCache, overridden, values])

  const lookupOptions = (name: string, config: FormField): Option[] => {
    const opts = config.options
      ? config.options.map((option) => ({ id: option, label: config.option_labels?.[option] ?? option }))
      : optionOverrides?.[name] ?? optionsCache[name] ?? []
    const storedId = values[name] == null || values[name] === '' ? '' : String(values[name])
    const fallbackLabel = lookupLabels[name]
    if (storedId && fallbackLabel && !opts.some((option) => optionIdEquals(option.id, storedId))) {
      return [{ id: storedId, label: fallbackLabel }, ...opts]
    }
    return opts
  }

  const autoHint = (name: string, config: FormField) => {
    if (!config.auto_parts?.length) return null
    const canRegenerate = overridden[name] === true || Boolean(hydrateKey && values[name])
    return (
      <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
        Filled as Case name-Amount-Date.{' '}
        {canRegenerate ? (
          <button
            type="button"
            className="font-medium text-accent hover:underline"
            onClick={() => setOverridden((prev) => ({ ...prev, [name]: false }))}
          >
            Use generated description
          </button>
        ) : (
          'You can edit it if needed.'
        )}
      </p>
    )
  }

  const renderField = (name: string, config: FormField) => {
    const val = values[name]

    if (config.type === 'boolean') {
      return (
        <div key={name} className="sm:col-span-2 xl:col-span-1">
          <Checkbox label={config.label} checked={Boolean(val)} onChange={(v) => onChange(name, v)} />
        </div>
      )
    }

    if (config.type === 'select_or_custom') {
      const presets = config.options || []
      const customLabel = config.custom_option || 'Custom'
      const stored = val == null || val === '' ? '' : String(val)
      const isPreset = presets.includes(stored)
      const inCustom = customMode[name] === true || (customMode[name] !== false && stored !== '' && !isPreset)
      const choice = inCustom ? customLabel : stored
      const choices = [...presets.map((option) => ({ id: option, label: option })), { id: customLabel, label: customLabel }]
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)}>
          <SearchSelect
            value={choice}
            options={choices}
            onChange={(next) => {
              if (next == null || next === '') {
                setCustomMode((prev) => ({ ...prev, [name]: false }))
                onChange(name, null)
                return
              }
              if (next === customLabel) {
                setCustomMode((prev) => ({ ...prev, [name]: true }))
                onChange(name, isPreset ? null : stored || null)
                return
              }
              setCustomMode((prev) => ({ ...prev, [name]: false }))
              onChange(name, next)
            }}
            placeholder="— Select —"
            allowEmpty={!config.required}
          />
          {inCustom ? (
            <Input
              className="mt-2"
              placeholder="Type the opportunity type"
              value={isPreset ? '' : stored}
              onChange={(e) => onChange(name, e.target.value === '' ? null : e.target.value)}
            />
          ) : null}
        </Field>
      )
    }

    if (lumen && config.type === 'select' && !config.source_table && (config.options?.length ?? 0) >= 2 && (config.options?.length ?? 0) <= 4) {
      const choices = lookupOptions(name, config)
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)} className={choices.map((c) => c.label).join('').length > 26 ? 'sm:col-span-2' : ''}>
          <SegmentedChoice
            label={config.label}
            value={val == null ? '' : String(val)}
            options={choices}
            allowClear={!config.required}
            disabled={Boolean(lockedFields?.[name])}
            onChange={(next) => onChange(name, next)}
          />
          {config.hint && <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">{config.hint}</p>}
        </Field>
      )
    }

    if (config.type === 'select' || (config.source_table && config.type !== 'dependent_select')) {
      const isLookup = Boolean(config.source_table)
      const storedId = val == null || val === '' ? '' : String(val)
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)}>
          <SearchSelect
            value={storedId}
            options={lookupOptions(name, config)}
            onChange={(next) => onChange(name, next)}
            placeholder={isLookup ? `— Select ${config.label.toLowerCase()} —` : '— Select —'}
            allowEmpty={(isLookup || !config.required) && !lockedFields?.[name]}
            fallbackLabel={isLookup ? lookupLabels[name] : undefined}
            disabled={Boolean(lockedFields?.[name])}
          />
          {lockedFields?.[name] && <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">{lockedFields[name]}</p>}
          {config.hint && !lockedFields?.[name] && <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">{config.hint}</p>}
        </Field>
      )
    }

    if (config.type === 'state') {
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)}>
          <SearchSelect
            value={(val as string) ?? ''}
            options={states.map((state) => ({ id: state, label: state }))}
            onChange={(next) => onChange(name, next)}
            placeholder="— Select state —"
          />
        </Field>
      )
    }

    if (config.type === 'dependent_select') {
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)}>
          <SearchSelect
            value={(val as string) ?? ''}
            options={cities.map((city) => ({ id: city, label: city }))}
            onChange={(next) => onChange(name, next)}
            placeholder="— Select city —"
            disabled={!values[config.depends_on || '']}
          />
        </Field>
      )
    }

    if (config.type === 'textarea') {
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)} className={lumen ? 'sm:col-span-2' : 'sm:col-span-2 xl:col-span-3'}>
          <Textarea
            value={val == null ? '' : String(val)}
            onChange={(e) => {
              if (config.auto_parts?.length) setOverridden((prev) => ({ ...prev, [name]: true }))
              onChange(name, e.target.value === '' ? null : e.target.value)
            }}
          />
          {autoHint(name, config)}
        </Field>
      )
    }

    if (config.money && !config.readonly && !config.compute_from?.length) {
      return (
        <Field key={name} label={config.label} required={Boolean(config.required)}>
          <MoneyInput value={val as string | number | null | undefined} onChange={(raw) => onChange(name, raw === '' ? null : Number(raw))} />
          {config.hint && <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">{config.hint}</p>}
        </Field>
      )
    }

    const inputType =
      config.type === 'date' ? 'date' : config.type === 'number' || config.type === 'integer' ? 'number' : 'text'
    const isComputed = Boolean(config.compute_from?.length || config.auto_parts?.length)
    const isAutoComputed = config.compute_op === 'difference' || config.compute_op === 'month_year'
    const isReadOnly = Boolean(config.readonly) || isAutoComputed

    return (
      <Field
        key={name}
        label={config.label}
        required={Boolean(config.required)}
        className={config.auto_parts?.length ? (lumen ? 'sm:col-span-2' : 'sm:col-span-2 xl:col-span-3') : ''}
      >
        <Input
          type={inputType}
          step={config.type === 'number' ? 'any' : config.type === 'integer' ? '1' : undefined}
          readOnly={isReadOnly}
          className={isReadOnly ? 'bg-muted' : ''}
          value={val == null ? '' : config.type === 'date' ? String(val).slice(0, 10) : String(val)}
          onChange={(e) => {
            if (isReadOnly) return
            if (isComputed) setOverridden((prev) => ({ ...prev, [name]: true }))
            onChange(
              name,
              e.target.value === ''
                ? null
                : config.type === 'integer'
                  ? Number(e.target.value)
                  : config.type === 'number'
                    ? Number(e.target.value)
                    : e.target.value,
            )
          }}
        />
        {lumen && config.type === 'date' && !isReadOnly && <QuickDates onPick={(day) => onChange(name, day)} />}
        {(config.readonly || config.hint) && (
          <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
            {config.hint ?? 'Set automatically when the status changes.'}
          </p>
        )}
        {config.compute_op === 'difference' && (
          <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
            Auto-calculated as final reading − initial reading.
          </p>
        )}
        {config.compute_op === 'month_year' && (
          <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
            Auto-calculated from transaction date (YYYY-MM).
          </p>
        )}
        {autoHint(name, config)}
      </Field>
    )
  }

  const classic = (
    <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-3">
      {beforeFields.map(([name, config]) => renderField(name, config))}
      {hasBreakdown && (
        <div className="sm:col-span-2 xl:col-span-3">
          <AmountBreakdownBox
            values={values}
            onChange={onChange}
            amountField={amountField}
            totalOverridden={Boolean(overridden.amount_after_tax_gst)}
            onTotalOverride={(value) => setOverridden((prev) => ({ ...prev, amount_after_tax_gst: value }))}
          />
        </div>
      )}
      {afterFields.map(([name, config]) => renderField(name, config))}
    </div>
  )
  if (!lumen) return classic

  // Lumen: the same fields in the same order of importance, gathered into sections a person can take one at a time.
  const shown = [...beforeFields, ...afterFields]
  const kindOfField = (config: FormField): 'notes' | 'dates' | 'amounts' | 'details' =>
    config.type === 'textarea' ? 'notes' : config.type === 'date' ? 'dates' : config.money || config.type === 'number' || config.type === 'integer' || config.compute_from?.length ? 'amounts' : 'details'
  const sections: { id: string; title: string; hint?: string; fields: [string, FormField][] }[] = [
    { id: 'details', title: 'Details', fields: shown.filter(([, c]) => kindOfField(c) === 'details') },
    { id: 'amounts', title: 'Amounts', hint: 'Totals are worked out for you', fields: shown.filter(([, c]) => kindOfField(c) === 'amounts') },
    { id: 'dates', title: 'Dates', fields: shown.filter(([, c]) => kindOfField(c) === 'dates') },
    { id: 'notes', title: 'Notes', fields: shown.filter(([, c]) => kindOfField(c) === 'notes') },
  ].filter((section) => section.fields.length > 0 || (section.id === 'amounts' && hasBreakdown))
  const needed = entries.filter(([, c]) => c.required && !c.readonly && !c.compute_from?.length && !c.auto_parts?.length)
  const done = needed.filter(([name]) => values[name] != null && values[name] !== '').length

  return (
    <div className="space-y-4">
      {needed.length > 0 && <FormProgress done={done} total={needed.length} />}
      {sections.map((section) => (
        <FormSection key={section.id} title={sections.length > 1 ? section.title : undefined} hint={sections.length > 1 ? section.hint : undefined}>
          <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2">
            {section.id === 'amounts' && hasBreakdown && (
              <div className="sm:col-span-2">
                <AmountBreakdownBox
                  values={values}
                  onChange={onChange}
                  amountField={amountField}
                  totalOverridden={Boolean(overridden.amount_after_tax_gst)}
                  onTotalOverride={(value) => setOverridden((prev) => ({ ...prev, amount_after_tax_gst: value }))}
                />
              </div>
            )}
            {section.fields.map(([name, config]) => renderField(name, config))}
          </div>
        </FormSection>
      ))}
    </div>
  )
}
