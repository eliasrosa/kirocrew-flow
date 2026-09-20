import type { CSSProperties } from 'react'
import IssueCard from './IssueCard'
import type { Columns, DispatchHandler, Issue } from './types'
import { sectionLabelStyle } from './types'

// ---------------------------------------------------------------------------
// AgentsSection — seção "Agentes" com dois painéis verticais:
//   Desenvolvimento -> Aguardando (columns.todo, COM Dispatch) / Trabalhando (columns.dev)
//   Code Review     -> Aguardando (review não-running) / Trabalhando (review running)
//
// Decisões documentadas:
//  - "Trabalhando" do Desenvolvimento mostra TODAS as issues de columns.dev
//    (não só as running); o badge "running" no card distingue quem está ativo.
//    Assim nenhuma issue em dev some do board.
//  - review e review-running compartilham a mesma coluna do backend
//    (columns.review); dividimos aqui pelo campo issue.running.
//  - columns.review_ok (aguardando merge) e columns.blocked são exibidas numa
//    faixa compacta abaixo dos painéis para que nada suma do board.
// ---------------------------------------------------------------------------

const subColStyle: CSSProperties = {
  flex: 1,
  minWidth: 200,
}

const subColHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  marginBottom: 10,
  fontSize: 12,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  opacity: 0.7,
}

const emptyStyle: CSSProperties = {
  fontSize: 12,
  opacity: 0.4,
  textAlign: 'center',
  padding: '16px 0',
}

interface SubColumnProps {
  title: string
  issues: Issue[]
  showDispatch?: boolean
  onDispatch?: DispatchHandler
  dispatchingKey?: string
}

function SubColumn({ title, issues, showDispatch, onDispatch, dispatchingKey }: SubColumnProps) {
  return (
    <div style={subColStyle}>
      <div style={subColHeaderStyle}>
        <span>{title}</span>
        <span style={{ opacity: 0.6 }}>({issues.length})</span>
      </div>
      {issues.length === 0 ? (
        <div style={emptyStyle}>—</div>
      ) : (
        issues.map((issue) => {
          const key = `${issue.repo}#${issue.number}`
          return (
            <IssueCard
              key={key}
              issue={issue}
              showDispatch={showDispatch}
              onDispatch={onDispatch}
              dispatching={dispatchingKey === key}
            />
          )
        })
      )}
    </div>
  )
}

interface PanelProps {
  title: string
  children: React.ReactNode
}

function Panel({ title, children }: PanelProps) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 440,
        border: '1px solid rgba(128,128,128,0.25)',
        borderRadius: 10,
        padding: '14px 16px',
        background: 'rgba(128,128,128,0.04)',
      }}
    >
      {/* rótulo do painel com font-weight menor (ver types.ts sectionLabelStyle) */}
      <div style={{ ...sectionLabelStyle, marginBottom: 12 }}>{title}</div>
      <div style={{ display: 'flex', gap: 12 }}>{children}</div>
    </div>
  )
}

// Faixa compacta para review_ok (aguardando merge) e blocked.
interface StripProps {
  title: string
  issues: Issue[]
  color: string
}

function Strip({ title, issues, color }: StripProps) {
  if (issues.length === 0) return null
  return (
    <div style={{ flex: 1, minWidth: 260 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 8,
          paddingBottom: 6,
          borderBottom: `2px solid ${color}`,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {title}
        </span>
        <span
          style={{
            background: color,
            color: '#fff',
            borderRadius: 10,
            padding: '1px 7px',
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {issues.length}
        </span>
      </div>
      {issues.map((issue) => (
        <IssueCard key={`${issue.repo}#${issue.number}`} issue={issue} />
      ))}
    </div>
  )
}

export interface AgentsSectionProps {
  columns: Columns
  onDispatch: DispatchHandler
  dispatchingKey?: string
}

export default function AgentsSection({ columns, onDispatch, dispatchingKey }: AgentsSectionProps) {
  const reviewWaiting = columns.review.filter((i) => !i.running)
  const reviewWorking = columns.review.filter((i) => i.running)

  return (
    <div style={{ marginTop: 24 }}>
      {/* rótulo da seção com font-weight menor (ver types.ts sectionLabelStyle) */}
      <div style={{ ...sectionLabelStyle, fontSize: 18, marginBottom: 14 }}>Agentes</div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <Panel title="Desenvolvimento">
          <SubColumn
            title="Aguardando"
            issues={columns.todo}
            showDispatch
            onDispatch={onDispatch}
            dispatchingKey={dispatchingKey}
          />
          <SubColumn title="Trabalhando" issues={columns.dev} />
        </Panel>

        <Panel title="Code Review">
          <SubColumn title="Aguardando" issues={reviewWaiting} />
          <SubColumn title="Trabalhando" issues={reviewWorking} />
        </Panel>
      </div>

      {/* Faixa compacta: aguardando merge (review_ok) e bloqueadas */}
      {(columns.review_ok.length > 0 || columns.blocked.length > 0) && (
        <div style={{ display: 'flex', gap: 16, marginTop: 20, flexWrap: 'wrap' }}>
          <Strip title="Aguardando merge" issues={columns.review_ok} color="#0ea5e9" />
          <Strip title="Blocked" issues={columns.blocked} color="#dc2626" />
        </div>
      )}
    </div>
  )
}
