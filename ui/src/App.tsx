import { useAppApi } from '@kirocrew/app-sdk'
import { PageHeader, Btn } from '@kirocrew/app-sdk/ui'
import { useState, useEffect, useCallback } from 'react'
import type { Columns, IssuesResponse } from './types'
import { emptyColumns } from './types'
import WaitingSection from './WaitingSection'
import AgentsSection from './AgentsSection'

// ---------------------------------------------------------------------------
// Mock data — usado quando o backend.routes ainda não está disponível
// (issue #170: backend.routes não registra rotas para apps de terceiros)
// ---------------------------------------------------------------------------

const MOCK_COLUMNS: Columns = {
  spec: [
    { number: 97, title: 'Exemplo: issue aguardando SPEC', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 15, labels: ['crewflow:spec'], blocked: false, running: false },
  ],
  ready: [
    { number: 98, title: 'Exemplo: aguardando definição de produto/TL', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 60, labels: ['crewflow:ready'], blocked: false, running: false },
  ],
  todo: [
    { number: 99, title: 'Exemplo: feature aguardando dev', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 45, labels: ['crewflow:feature', 'crewflow:p2'], blocked: false, running: false },
  ],
  dev: [
    { number: 100, title: 'Exemplo: issue em implementação', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 120, labels: ['crewflow:bug', 'crewflow:p1'], blocked: false, running: true },
  ],
  review: [
    { number: 101, title: 'Exemplo: PR aguardando review', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 30, labels: ['crewflow:feature'], blocked: false, running: false },
  ],
  review_ok: [
    { number: 103, title: 'Exemplo: aprovado, aguardando merge', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 10, labels: ['crewflow:review-ok'], blocked: false, running: false },
  ],
  done: [],
  blocked: [
    { number: 102, title: 'Exemplo: issue bloqueada', repo: 'eliasrosa/kirocrew-flow', url: '', age_min: 240, labels: ['crewflow:debt'], blocked: true, running: false },
  ],
}

const DEFAULT_SQUAD_NAME = 'KiroCrew Flow'

export default function CrewFlow() {
  const api = useAppApi()
  const [columns, setColumns] = useState<Columns>(emptyColumns())
  const [squadName, setSquadName] = useState<string>('')
  const [project, setProject] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isMock, setIsMock] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [dispatchingKey, setDispatchingKey] = useState<string | null>(null)

  const load = useCallback(() => {
    return api
      .get('/api/apps/kirocrew-flow/issues')
      .then((d: IssuesResponse) => {
        setColumns(d.columns ?? emptyColumns())
        setSquadName(d.squad_name ?? '')
        setProject(d.project ?? '')
        setLastUpdate(new Date())
        setError(null)
        setIsMock(false)
      })
      .catch((err: unknown) => {
        const msg = String(err)
        // 404 = backend.routes não disponível para apps de terceiros (issue #170)
        // Usar dados mock para permitir desenvolvimento da UI
        if (msg.includes('404') || msg.includes('not found')) {
          setColumns(MOCK_COLUMNS)
          setSquadName('')
          setProject('')
          setIsMock(true)
          setError(null)
        } else {
          setError(msg)
        }
      })
      .finally(() => {
        setLoading(false)
      })
  }, [api])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  const handleDispatch = useCallback(
    async (repo: string, number: number | string) => {
      const key = `${repo}#${number}`
      setDispatchingKey(key)
      try {
        await api.post('/api/apps/kirocrew-flow/dispatch', { repo, number: Number(number) })
        await load()
      } catch (err) {
        console.error('dispatch failed:', err)
      } finally {
        setDispatchingKey(null)
      }
    },
    [api, load],
  )

  // Título multi-squad: "Flow - {squad} / {project}", com fallback a "KiroCrew Flow".
  const effectiveSquad = squadName || DEFAULT_SQUAD_NAME
  const title = project ? `Flow - ${effectiveSquad} / ${project}` : `Flow - ${effectiveSquad}`

  const totalActive =
    columns.spec.length +
    columns.ready.length +
    columns.todo.length +
    columns.dev.length +
    columns.review.length +
    columns.review_ok.length +
    columns.blocked.length

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400 }}>
      <PageHeader
        title={title}
        subtitle={
          loading
            ? 'Carregando…'
            : error
            ? `Erro: ${error}`
            : isMock
            ? '⚠️ Modo demo — backend indisponível (issue #170)'
            : lastUpdate
            ? `${totalActive} issues ativas · atualizado ${lastUpdate.toLocaleTimeString()}`
            : ''
        }
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            {/* Placeholders visíveis: abrirão a futura página de Squads / regras de roteamento */}
            <Btn size="sm" variant="secondary" onClick={() => console.log('Configurações (placeholder)')}>
              Configurações
            </Btn>
            <Btn size="sm" variant="secondary" onClick={() => console.log('Rules (placeholder)')}>
              Rules
            </Btn>
            <Btn size="sm" variant="secondary" onClick={load} disabled={loading}>
              ↻ Atualizar
            </Btn>
          </div>
        }
      />

      {/* Áreas de espera humana: Aguardando SPEC / Aguardando definição */}
      <WaitingSection columns={columns} />

      {/* Seção Agentes: Desenvolvimento + Code Review */}
      <AgentsSection columns={columns} onDispatch={handleDispatch} dispatchingKey={dispatchingKey ?? undefined} />
    </div>
  )
}
