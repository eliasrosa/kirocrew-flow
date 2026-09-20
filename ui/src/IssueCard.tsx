import { Card, Btn } from '@kirocrew/app-sdk/ui'
import type { DispatchHandler, Issue } from './types'
import { formatAge, repoShort } from './types'

// ---------------------------------------------------------------------------
// IssueCard — extraído do App.tsx (mesmas props e renderização)
// ---------------------------------------------------------------------------

export interface IssueCardProps {
  issue: Issue
  showDispatch?: boolean
  onDispatch?: DispatchHandler
  dispatching?: boolean
}

export default function IssueCard({ issue, showDispatch, onDispatch, dispatching }: IssueCardProps) {
  return (
    <Card style={{ marginBottom: 8, padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: 12, opacity: 0.6, whiteSpace: 'nowrap' }}>
              #{issue.number}
            </span>
            <span style={{ fontWeight: 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {issue.title}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, opacity: 0.6 }}>
            <span>{repoShort(issue.repo)}</span>
            {issue.age_min > 0 && (
              <span>⏱ {formatAge(issue.age_min)}</span>
            )}
            {issue.running && (
              <span style={{ color: '#f97316' }}>● running</span>
            )}
          </div>
        </div>
        {showDispatch && onDispatch && (
          <Btn
            size="sm"
            variant="secondary"
            disabled={dispatching}
            onClick={() => onDispatch(issue.repo, issue.number)}
            style={{ flexShrink: 0, fontSize: 11 }}
          >
            {dispatching ? '...' : 'Dispatch'}
          </Btn>
        )}
      </div>
      {issue.url && (
        <a
          href={issue.url}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 11, opacity: 0.5, textDecoration: 'none', display: 'block', marginTop: 4 }}
        >
          🔗 Ver issue
        </a>
      )}
    </Card>
  )
}
