import { useAppApi } from '@kirocrew/app-sdk'
import { Card, PageHeader, StatCard, Btn } from '@kirocrew/app-sdk/ui'
import { useState, useEffect } from 'react'

interface IssueCard {
  number: number
  title: string
  repo: string
  url?: string
  age_min?: number | null
}

type Columns = Record<string, IssueCard[]>

// Ordem das colunas de estágio + a coluna blocked à parte.
const STAGE_ORDER = ['todo', 'dev', 'review', 'reviewed', 'done'] as const

const STAGE_LABELS: Record<string, string> = {
  todo: 'To Do',
  dev: 'Dev',
  review: 'Review',
  reviewed: 'Reviewed',
  done: 'Done',
  blocked: 'Blocked',
}

// Formata o tempo no estágio a partir de age_min (minutos). Degrada para '—'
// quando o backend não conseguiu obter o valor (null/undefined).
function formatAge(ageMin?: number | null): string {
  if (ageMin === null || ageMin === undefined || Number.isNaN(ageMin)) return '—'
  if (ageMin < 60) return `${Math.round(ageMin)}m`
  const hours = ageMin / 60
  if (hours < 24) return `${Math.round(hours)}h`
  const days = hours / 24
  return `${Math.round(days)}d`
}

export default function CrewFlow() {
  const api = useAppApi()
  const [columns, setColumns] = useState<Columns>({})

  const load = () =>
    api
      .get('/api/apps/kirocrew-flow/issues')
      .then((d: { columns?: Columns }) => setColumns(d.columns || {}))

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const dispatch = (card: IssueCard) =>
    api
      .post('/api/apps/kirocrew-flow/dispatch', { repo: card.repo, number: card.number })
      .then(load)

  const renderCard = (card: IssueCard, stage: string) => (
    <Card key={`${card.repo}#${card.number}`}>
      <div style={{ fontWeight: 600 }}>
        #{card.number} {card.title}
      </div>
      <div style={{ fontSize: 12, opacity: 0.7 }}>{card.repo}</div>
      <div style={{ fontSize: 12, opacity: 0.7 }}>em estágio: {formatAge(card.age_min)}</div>
      {stage === 'todo' && (
        <div style={{ marginTop: 8 }}>
          <Btn onClick={() => dispatch(card)}>force dispatch</Btn>
        </div>
      )}
    </Card>
  )

  const renderColumn = (stage: string) => {
    const cards = columns[stage] || []
    return (
      <div key={stage} style={{ minWidth: 220, flex: 1 }}>
        <StatCard label={STAGE_LABELS[stage] ?? stage} value={cards.length} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {cards.map((card) => renderCard(card, stage))}
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="KiroCrew Flow" />
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', overflowX: 'auto' }}>
        {STAGE_ORDER.map((stage) => renderColumn(stage))}
      </div>
      <div style={{ marginTop: 24 }}>{renderColumn('blocked')}</div>
    </div>
  )
}
