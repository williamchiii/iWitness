import { useEffect, useState } from 'react'
import { onUserChange } from './auth'
import type { User } from './auth'

// The signed-in user. `ready` turns true once the session has been restored,
// so a page can tell "not logged in" apart from "still checking".
export function useUser() {
  const [state, setState] = useState<{ user: User | null; ready: boolean }>({ user: null, ready: false })
  useEffect(() => onUserChange((user) => setState({ user, ready: true })), [])
  return state
}
