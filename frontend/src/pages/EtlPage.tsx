import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { EtlView, type TallyNote } from '../components/etl/EtlView'
import type { RunFilters } from '../components/etl/RunTable'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import type { EtlPipeline, EtlPipelineKey, EtlRun, EtlRunDetail } from '../types'

const PAGE = 25
const FAST_MS = 2000
const SLOW_MS = 15000

/** The current time, ticking every second, so "3 s ago" stays true while the page is open. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/**
 * Fetches the pipelines and their runs and keeps them fresh: every 2 seconds while something is running, every 15
 * otherwise. Runs happen on the server, so they carry on if the page is left. Drawing is left to EtlView.
 */
export function EtlPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const [search, setSearch] = useSearchParams()
  const now = useNow()
  const [pipelines, setPipelines] = useState<EtlPipeline[] | null>(null)
  const [runs, setRuns] = useState<EtlRun[] | null>(null)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [filters, setFilters] = useState<RunFilters>({ pipeline: search.get('pipeline') ?? '', status: '', trigger: '' })
  const [progress, setProgress] = useState<Record<string, EtlRunDetail>>({})
  const [openId, setOpenId] = useState<number | null>(() => Number(search.get('run')) || null)
  const [detail, setDetail] = useState<EtlRunDetail | null>(null)
  const [detailError, setDetailError] = useState('')
  const [confirm, setConfirm] = useState<{ pipeline: EtlPipeline; table?: string } | null>(null)
  const [started, setStarted] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [moreLoading, setMoreLoading] = useState(false)
  const [tally, setTally] = useState<TallyNote | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [selected, setSelected] = useState(search.get('pipeline') ?? '')
  const wasRunning = useRef(false)

  const anyRunning = (pipelines ?? []).some((p) => p.running)
  const anyRunningRef = useRef(false)
  anyRunningRef.current = anyRunning

  const load = useCallback(async () => {
    try {
      const [overview, history] = await Promise.all([api.etlPipelines(), api.etlRuns({ ...filters, limit: PAGE * pages })])
      setPipelines(overview.pipelines)
      setRuns(history.runs)
      setTotal(history.total)
      const going = overview.pipelines.filter((p) => p.running && p.last_run)
      const details = await Promise.all(going.map((p) => api.etlRun(p.last_run!.id).catch(() => null)))
      setProgress(Object.fromEntries(going.flatMap((p, i) => (details[i] ? [[p.key, details[i] as EtlRunDetail]] : []))))
      setUpdatedAt(Date.now())
      setError('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setMoreLoading(false)
    }
  }, [filters, pages])

  useEffect(() => {
    let timer: number | undefined
    let live = true
    const tick = async () => {
      await load()
      if (live) timer = window.setTimeout(tick, anyRunningRef.current ? FAST_MS : SLOW_MS)
    }
    void tick()
    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [load, generation])

  // The run open in the drawer, followed every 2 seconds while it is going.
  useEffect(() => {
    setDetail(null)
    setDetailError('')
    if (openId === null) return
    let live = true
    let timer: number | undefined
    const fetchOne = () =>
      api
        .etlRun(openId)
        .then((found) => {
          if (!live) return
          setDetail(found)
          if (found.status === 'running') timer = window.setTimeout(fetchOne, FAST_MS)
        })
        .catch((e: Error) => live && setDetailError(e.message))
    void fetchOne()
    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [openId])

  const canSeeTally = Boolean(user?.can_etl)
  const loadTally = useCallback(() => {
    if (!canSeeTally) return
    api
      .tallyStatus()
      .then((s) => setTally({ running: s.running, company: s.company, warning: s.warning, error: s.error }))
      .catch(() => setTally(null))
  }, [canSeeTally])

  useEffect(() => {
    loadTally()
  }, [loadTally, generation])
  useEffect(() => {
    // A run just finished: Tally may have been opened or closed meanwhile, so look again.
    if (wasRunning.current && !anyRunning) loadTally()
    wasRunning.current = anyRunning
  }, [anyRunning, loadTally])

  const setParam = (name: string, value: string | null) => {
    const params = new URLSearchParams(search)
    if (value) params.set(name, value)
    else params.delete(name)
    setSearch(params, { replace: true })
  }

  const start = async () => {
    if (!confirm) return
    const { pipeline, table } = confirm
    setConfirm(null)
    setError('')
    try {
      const { run_id } = await api.startEtl(pipeline.key, table)
      setStarted(run_id)
      setOpenId(null)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const selectPipeline = (key: EtlPipelineKey) => {
    setSelected(key)
    document.getElementById(`pipeline-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return (
    <EtlView
      pipelines={pipelines}
      progress={progress}
      runs={runs}
      total={total}
      filters={filters}
      moreLoading={moreLoading}
      tally={tally}
      updatedAt={updatedAt}
      now={now}
      error={error}
      started={started}
      selectedPipeline={selected}
      openRun={{ id: openId, detail, error: detailError }}
      confirm={confirm}
      onFilters={(next) => {
        setPages(1)
        setFilters(next)
        setSelected(next.pipeline)
        setParam('pipeline', next.pipeline || null)
      }}
      onMore={() => {
        setMoreLoading(true)
        setPages((n) => n + 1)
      }}
      onOpenRun={(id) => {
        setOpenId(id)
        setParam('run', id === null ? null : String(id))
      }}
      onRun={(pipeline, table) => setConfirm({ pipeline, table })}
      onConfirm={() => void start()}
      onCancelConfirm={() => setConfirm(null)}
      onDismissError={() => setError('')}
      onDismissStarted={() => setStarted(null)}
      onSelectPipeline={selectPipeline}
    />
  )
}
