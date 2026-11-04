import { useState, type ReactNode } from 'react'
import { Check, ChevronDown, Cloud, Cpu, LoaderCircle, TriangleAlert, Zap } from 'lucide-react'
import { aiApi } from '../../api/client'
import { useAssistant } from '../../ai/AssistantContext'
import { providerLabel } from '../../ai/labels'
import { useAuth } from '../../context/AuthContext'
import type { AiCloudPolicy, AiHealth } from '../../types'
import { Button } from '../ui/Button'
import { Card, CardHeader } from '../ui/Card'
import { Switch } from '../ui/Field'

const LOCAL_STATE: Record<string, { label: string; tone: string }> = {
  ok: { label: 'Running', tone: 'bg-positive-dim text-positive' },
  unreachable: { label: 'Not running', tone: 'bg-negative-dim text-negative' },
  no_model: { label: 'No model installed', tone: 'bg-warning-dim text-warning' },
  model_missing: { label: 'Model not installed', tone: 'bg-warning-dim text-warning' },
  error: { label: 'Problem', tone: 'bg-negative-dim text-negative' },
}

function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{children}</span>
}

function Row({ icon: Icon, title, badge, children }: { icon: typeof Cpu; title: string; badge: ReactNode; children: ReactNode }) {
  return (
    <div className="flex gap-3.5 py-4 first:pt-0 last:pb-0">
      <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-[color:var(--color-text-muted)]">
        <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="t-h3">{title}</h4>
          {badge}
        </div>
        {children}
      </div>
    </div>
  )
}

function Code({ children }: { children: string }) {
  return <code className="block overflow-x-auto rounded-lg bg-muted px-3 py-2 font-mono text-[12px] leading-relaxed">{children}</code>
}

/** Settings → AI Copilot → how answers are made: the application itself, the model on this computer, and cloud AI if it is allowed at all. */
export function RoutingSettings() {
  const { user } = useAuth()
  const { status, reloadStatus } = useAssistant()
  const [checking, setChecking] = useState(false)
  const [health, setHealth] = useState<AiHealth | null>(null)
  const [help, setHelp] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  if (!status) return null
  const isAdmin = user?.role === 'admin'
  const { local, cloud, policies } = status.routing
  const localState = health?.local ?? { state: local.state, model: local.model, latency_ms: null, detail: local.detail, installed: local.installed }
  const shown = LOCAL_STATE[localState.state] ?? LOCAL_STATE.error
  const cloudAllowedByOrg = cloud.switched_on && cloud.policy !== 'local_only'

  const check = async () => {
    setChecking(true)
    setError('')
    try {
      setHealth(await aiApi.health())
      await reloadStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The check could not be run.')
    } finally {
      setChecking(false)
    }
  }

  const setPolicy = async (mode: AiCloudPolicy) => {
    setSaving(true)
    setError('')
    try {
      await aiApi.setPolicy(mode)
      await reloadStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const allowCloud = async (value: boolean) => {
    setError('')
    try {
      await aiApi.saveSettings({ allow_cloud: value })
      await reloadStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That could not be saved.')
    }
  }

  return (
    <Card accent="blue">
      <CardHeader title="How answers are made" subtitle="The cheapest way that works is used first. Your data stays on this computer unless cloud AI is explicitly allowed." />
      {error && (
        <p role="alert" className="mb-3 flex items-center gap-2 rounded-lg bg-negative-dim px-3 py-2 text-sm text-negative">
          <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
      <div className="divide-y divide-[color:var(--color-border)]">
        <Row icon={Zap} title="Orion directly" badge={<Badge tone="bg-positive-dim text-positive">Always on</Badge>}>
          <p className="t-small text-[color:var(--color-text-muted)]">
            Figures, rankings, comparisons, who owes what, records, reminders and reports are worked out straight from your data by the application. No AI model is involved and nothing leaves this computer.
          </p>
        </Row>

        <Row icon={Cpu} title="Local AI" badge={<Badge tone={shown.tone}>{shown.label}</Badge>}>
          <p className="t-small text-[color:var(--color-text-muted)]">
            {localState.state === 'ok'
              ? `A model on this computer (${localState.model}) handles open-ended questions. It never sends anything out.`
              : local.provider === 'none'
                ? 'No local AI model is configured. Open-ended questions need one; the questions above work without it.'
                : 'Open-ended questions need an AI model running on this computer. It is not available right now; the questions above still work.'}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={check} disabled={checking}>
              {checking ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Check className="h-3.5 w-3.5" aria-hidden="true" />}
              Check now
            </Button>
            {health && <span className="t-caption">{health.local.state === 'ok' ? `Answered in ${health.local.latency_ms ?? '?'} ms` : (LOCAL_STATE[health.local.state] ?? LOCAL_STATE.error).label}</span>}
            <button type="button" onClick={() => setHelp((v) => !v)} aria-expanded={help} className="interactive inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline">
              How to set it up
              <ChevronDown className={`h-3.5 w-3.5 transition ${help ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>
          </div>
          {isAdmin && localState.detail && <p className="t-caption break-words">{localState.detail}</p>}
          {isAdmin && localState.installed.length > 0 && <p className="t-caption">Installed: {localState.installed.join(', ')}</p>}
          {help && (
            <ol className="t-small list-decimal space-y-2.5 pl-5 text-[color:var(--color-text-muted)]">
              <li>
                On the computer that runs Orion, install Ollama from <span className="font-semibold text-[color:var(--color-text)]">ollama.com/download</span> and let it start.
              </li>
              <li>
                Download a model. A small one for a computer without a graphics card:
                <Code>ollama pull qwen2.5:3b-instruct</Code>
                With more memory or a graphics card, a bigger one answers better (for example <span className="font-mono text-[12px]">qwen2.5:7b-instruct</span>). Pick one that supports tools.
              </li>
              <li>
                Tell Orion which one in the server settings file (<span className="font-mono text-[12px]">.env</span>), then restart the API:
                <Code>ORION_AI_LOCAL_MODEL=qwen2.5:3b-instruct</Code>
              </li>
              <li>Come back here and press “Check now”. The first answer is slower while the model loads.</li>
            </ol>
          )}
        </Row>

        <Row
          icon={Cloud}
          title="Cloud AI"
          badge={
            <Badge tone={cloud.usable_by_you ? 'bg-warning-dim text-warning' : 'bg-muted text-[color:var(--color-text-muted)]'}>
              {!cloud.switched_on ? 'Off' : cloud.usable_by_you ? 'Allowed for you' : cloudAllowedByOrg ? 'Needs your permission' : 'Not permitted'}
            </Badge>
          }
        >
          <p className="t-small text-[color:var(--color-text-muted)]">
            {!cloud.switched_on
              ? 'Not switched on for this server, so nothing is ever sent to a cloud AI service.'
              : cloud.policy === 'local_only'
                ? 'Switched on for this server, but your organisation’s policy keeps everything on this computer.'
                : 'Only used when the local AI cannot answer, never for private or restricted requests, and never beyond the budget. Names in your data are replaced before anything is sent.'}
          </p>
          {isAdmin && health?.cloud && (
            <p className="t-caption">
              Cloud check: {health.cloud.state === 'ok' ? `reachable (${health.cloud.model})` : `${health.cloud.state}${health.cloud.detail ? `: ${health.cloud.detail}` : ''}`}
            </p>
          )}
          {cloudAllowedByOrg && (
            <Switch
              label="Let cloud AI help with my hard questions"
              hint={`Your questions may be sent to ${providerLabel(cloud.provider)} when the local AI cannot answer them. Off unless you turn it on.`}
              checked={status.settings.allow_cloud}
              onChange={(value) => void allowCloud(value)}
            />
          )}
        </Row>
      </div>

      {isAdmin && (
        <div className="mt-5 space-y-4 border-t border-[color:var(--color-border)] pt-5">
          <div>
            <h4 className="t-h3">Organisation policy for cloud AI</h4>
            <p className="t-caption mt-0.5">Applies to everyone. Each person can only make it stricter for themselves.</p>
          </div>
          <div role="radiogroup" aria-label="Cloud AI policy" className="space-y-2">
            {policies.map((item) => {
              const [title, ...rest] = item.label.split(': ')
              const selected = cloud.policy === item.id
              return (
                <label
                  key={item.id}
                  className={`interactive flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 ${selected ? 'border-[color:var(--color-primary)] bg-accent-dim' : 'border-[color:var(--color-border)] hover:border-[color:var(--color-border-strong)]'} ${saving ? 'opacity-60' : ''}`}
                >
                  <input type="radio" name="cloud-policy" checked={selected} disabled={saving} onChange={() => void setPolicy(item.id)} className="mt-1 accent-[color:var(--color-primary)]" />
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold">{title}</span>
                    <span className="t-caption block">{rest.join(': ').replace(/^./, (c) => c.toUpperCase())}</span>
                  </span>
                </label>
              )
            })}
          </div>
          <dl className="t-small grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
            <dt className="text-[color:var(--color-text-muted)]">Cloud AI in the server settings</dt>
            <dd className="font-medium">{cloud.switched_on ? `On · ${cloud.provider}${cloud.model ? ` · ${cloud.model}` : ''}` : 'Off (ORION_AI_CLOUD_ESCALATION=0)'}</dd>
            {cloud.switched_on && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">API key</dt>
                <dd className={`font-medium ${cloud.key_present ? 'text-positive' : 'text-negative'}`}>{cloud.key_present ? 'Set on the server' : 'Not set'}</dd>
                <dt className="text-[color:var(--color-text-muted)]">Spent this month</dt>
                <dd className="t-num font-medium">
                  ${(cloud.spent_usd ?? 0).toFixed(2)} of ${(cloud.budget_usd ?? 0).toFixed(2)}
                  {(cloud.budget_usd ?? 0) <= 0 && <span className="t-caption ml-2">no budget set, so cloud AI is not used</span>}
                </dd>
                <dt className="text-[color:var(--color-text-muted)]">Per person a day</dt>
                <dd className="font-medium">{cloud.user_daily} cloud answers</dd>
              </>
            )}
          </dl>
          {status.admin && status.admin.routes.length > 0 && (
            <div className="overflow-x-auto">
              <p className="eyebrow mb-1.5">Last 7 days</p>
              <table className="w-full min-w-[26rem] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] text-[color:var(--color-text-muted)]">
                    <th className="py-1.5 font-semibold">Answered by</th>
                    <th className="py-1.5 text-right font-semibold">Answers</th>
                    <th className="py-1.5 text-right font-semibold">Average time</th>
                    <th className="py-1.5 text-right font-semibold">After a local attempt</th>
                    <th className="py-1.5 text-right font-semibold">Estimated cost</th>
                  </tr>
                </thead>
                <tbody>
                  {status.admin.routes.map((row) => (
                    <tr key={row.path} className="t-num border-t border-[color:var(--color-border)]">
                      <td className="py-1.5">{{ app: 'Orion directly', local: 'Local AI', cloud: 'Cloud AI', none: 'Could not answer' }[row.path] ?? row.path}</td>
                      <td className="py-1.5 text-right">{row.answers}</td>
                      <td className="py-1.5 text-right">{row.avg_ms >= 1000 ? `${(row.avg_ms / 1000).toFixed(1)} s` : `${row.avg_ms} ms`}</td>
                      <td className="py-1.5 text-right">{row.escalated}</td>
                      <td className="py-1.5 text-right">{row.cost_usd > 0 ? `$${row.cost_usd.toFixed(2)}` : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="t-caption mt-1.5">Only how each answer was made is recorded, never the question or the answer.</p>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
