import { useEffect } from 'react'

export function usePageTitle(title) {
  useEffect(() => {
    document.title = `${title} · Time-Travel DB & Bug Rewinder`
  }, [title])
}
