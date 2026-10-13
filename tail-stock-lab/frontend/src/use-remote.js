import { useEffect, useState } from 'react'

// Abort superseded requests and never render previous-query data under new filters.
export function useRemote(loader, args, revision = 0) {
  const argumentKey = JSON.stringify(args)
  const key = `${argumentKey}:${revision}`
  const [state, setState] = useState({ key: '', loading: true })
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    setState({ key, loading: true })
    loader(JSON.parse(argumentKey), { signal: controller.signal }).then(data => {
      if (active) setState({ key, data, loading: false })
    }).catch(error => {
      if (active && error.name !== 'AbortError') setState({ key, error: error.message, loading: false })
    })
    return () => { active = false; controller.abort() }
  }, [loader, key, argumentKey])
  return state.key === key ? state : { loading: true }
}
