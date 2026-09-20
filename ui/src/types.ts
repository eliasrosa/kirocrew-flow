import type { CSSProperties } from 'react'

// ---------------------------------------------------------------------------
// Tipos compartilhados da UI do Flow
// ---------------------------------------------------------------------------

export interface Issue {
  number: number | string
  title: string
  repo: string
  url: string
  age_min: number
  labels: string[]
  blocked: boolean
  running: boolean
}

// Colunas retornadas por GET /api/apps/kirocrew-flow/issues (contrato FEAT-001).
export interface Columns {
  spec: Issue[]
  ready: Issue[]
  todo: Issue[]
  dev: Issue[]
  review: Issue[]
  review_ok: Issue[]
  done: Issue[]
  blocked: Issue[]
}

// Resposta completa do endpoint /issues.
export interface IssuesResponse {
  squad_name?: string
  project?: string
  columns?: Columns
}

export type DispatchHandler = (repo: string, number: number | string) => Promise<void>

// Coluna vazia (todos os 8 keys) usada em useState inicial e no fallback do load().
export function emptyColumns(): Columns {
  return {
    spec: [],
    ready: [],
    todo: [],
    dev: [],
    review: [],
    review_ok: [],
    done: [],
    blocked: [],
  }
}

// ---------------------------------------------------------------------------
// Helpers de formatação
// ---------------------------------------------------------------------------

export function formatAge(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h`
  return `${Math.floor(minutes / (60 * 24))}d`
}

export function repoShort(repo: string): string {
  return repo.split('/').pop() ?? repo
}

// Rótulos de seção: o wireframe do Elias mostra uma fonte estilo "handwriting".
// A issue permite explicitamente "simplesmente um font-weight menor" como
// alternativa aceitável. Como o Elias não está disponível nesta sessão,
// implementamos a alternativa de font-weight menor (sem dependências de fonte
// externa). A fonte handwriting pode ser trocada aqui no futuro.
export const sectionLabelStyle: CSSProperties = {
  fontWeight: 400,
  fontSize: 15,
  opacity: 0.75,
  letterSpacing: '0.01em',
}
