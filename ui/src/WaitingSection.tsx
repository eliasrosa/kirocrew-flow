import type { CSSProperties } from 'react'
import IssueCard from './IssueCard'
import type { Columns, Issue } from './types'
import { sectionLabelStyle } from './types'

// ---------------------------------------------------------------------------
// WaitingSection — as duas áreas de espera humana lado a lado (1280px+):
//   "Aguardando SPEC"  -> columns.spec
//   "Aguardando definição de produto/TL" -> columns.ready
// Estes cards NÃO mostram o botão Dispatch (é espera humana, não de agente).
// ---------------------------------------------------------------------------

const areaStyle: CSSProperties = {
  flex: 1,
  minWidth: 380,
  border: '1px solid rgba(128,128,128,0.25)',
  borderRadius: 10,
  padding: '14px 16px',
  background: 'rgba(128,128,128,0.04)',
}

const emptyStyle: CSSProperties = {
  fontSize: 12,
  opacity: 0.4,
  textAlign: 'center',
  padding: '20px 0',
}

interface WaitingAreaProps {
  title: string
  issues: Issue[]
}

function WaitingArea({ title, issues }: WaitingAreaProps) {
  return (
    <div style={areaStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        {/* rótulo com font-weight menor (ver types.ts sectionLabelStyle) */}
        <span style={sectionLabelStyle}>{title}</span>
        <span style={{ fontSize: 12, opacity: 0.5 }}>({issues.length})</span>
      </div>
      {issues.length === 0 ? (
        <div style={emptyStyle}>Nenhuma issue aguardando</div>
      ) : (
        issues.map((issue) => (
          <IssueCard key={`${issue.repo}#${issue.number}`} issue={issue} />
        ))
      )}
    </div>
  )
}

export interface WaitingSectionProps {
  columns: Columns
}

export default function WaitingSection({ columns }: WaitingSectionProps) {
  return (
    <div style={{ display: 'flex', gap: 16, marginTop: 20, flexWrap: 'wrap' }}>
      <WaitingArea title="Aguardando SPEC" issues={columns.spec} />
      <WaitingArea title="Aguardando definição de produto/TL" issues={columns.ready} />
    </div>
  )
}
