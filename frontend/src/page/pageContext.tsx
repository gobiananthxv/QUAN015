/**
 * Live dashboard-state registry for the chatbot.
 *
 * Each view registers the charts it currently renders (id, title, type,
 * formula, data source, computed results). When the user asks the assistant
 * something, `getPageJson()` snapshots that state into the `page_json` payload
 * the backend sends to the model — so "what is this chart saying" is answered
 * from what is actually on screen, not from a generic price dump.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export type JsonScalar = string | number | boolean | null
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue }

export interface ChartDescriptor {
  id: string
  title: string
  chart_type: string
  formula?: string
  data_source?: string
  result: Record<string, JsonValue | undefined>
}

export interface PageJson {
  page_id: string
  page_name: string
  selected_asset: string
  charts: ChartDescriptor[]
}

interface PageContextValue {
  page: { id: string; name: string; asset: string }
  register: (charts: ChartDescriptor[]) => void
  remove: (ids: string[]) => void
  getPageJson: () => PageJson
}

const PageContext = createContext<PageContextValue | null>(null)

export function PageProvider({
  pageId,
  pageName,
  asset,
  children,
}: {
  pageId: string
  pageName: string
  asset: string
  children: ReactNode
}) {
  const [charts, setCharts] = useState<Record<string, ChartDescriptor>>({})
  const chartsRef = useRef(charts)
  chartsRef.current = charts

  const register = useCallback((descriptors: ChartDescriptor[]) => {
    setCharts((prev) => {
      const next = { ...prev }
      for (const d of descriptors) next[d.id] = d
      return next
    })
  }, [])

  const remove = useCallback((ids: string[]) => {
    setCharts((prev) => {
      const next = { ...prev }
      for (const id of ids) delete next[id]
      return next
    })
  }, [])

  const page = useMemo(() => ({ id: pageId, name: pageName, asset }), [pageId, pageName, asset])

  const getPageJson = useCallback(
    () => ({
      page_id: page.id,
      page_name: page.name,
      selected_asset: page.asset,
      charts: Object.values(chartsRef.current).sort((a, b) => a.title.localeCompare(b.title)),
    }),
    [page],
  )

  const value = useMemo(
    () => ({ page, register, remove, getPageJson }),
    [page, register, remove, getPageJson],
  )

  return <PageContext.Provider value={value}>{children}</PageContext.Provider>
}

export function usePage(): PageContextValue {
  const ctx = useContext(PageContext)
  if (!ctx) throw new Error('usePage must be used inside <PageProvider>')
  return ctx
}

/**
 * Registers `descriptors` with the page context when their content changes and
 * removes them when the view unmounts (so navigating away never leaves stale
 * charts in the registry). Content is compared by serialisation, so a view
 * re-rendering with an equivalent array does not churn the registry — and
 * cannot trigger a render loop.
 */
export function useRegisterCharts(descriptors: ChartDescriptor[]): void {
  const { register, remove } = usePage()
  const json = useMemo(() => JSON.stringify(descriptors), [descriptors])
  const lastJson = useRef<string | null>(null)
  const ids = useRef<string[]>([])

  useEffect(() => {
    if (json === lastJson.current) return
    lastJson.current = json
    if (ids.current.length) remove(ids.current)
    ids.current = descriptors.map((d) => d.id)
    if (descriptors.length) register(descriptors)
  }, [json, descriptors, register, remove])

  useEffect(
    () => () => {
      if (ids.current.length) remove(ids.current)
    },
    [remove],
  )
}