import { useCallback, useEffect, useRef, useState } from 'react'

// Matches duration-200 in POPUP_BACKDROP and POPUP_PANEL (lib/styles.ts).
const POPUP_EXIT_MS = 200

// Lets a popup play its exit before it's removed: close(then) marks it
// `closing` (styled with the *_OUT classes), then calls `then` once the exit
// has finished. `then` is what used to run immediately, such as onClose.
export function usePopupExit() {
  const [closing, setClosing] = useState(false)
  const after = useRef<() => void>(() => {})

  useEffect(() => {
    if (!closing) return
    const timer = setTimeout(() => after.current(), POPUP_EXIT_MS)
    return () => clearTimeout(timer)
  }, [closing])

  const close = useCallback((then: () => void) => {
    after.current = then
    setClosing(true)
  }, [])

  return { closing, close }
}
