import type { User as SupabaseUser } from '@supabase/supabase-js'
import { supabase } from './supabase'

export interface User {
  email: string
  name: string
}

export const isMockAuth = supabase === null

// Google puts the account's display name in user_metadata.
function toUser(user: SupabaseUser): User {
  const email = user.email ?? ''
  return { email, name: user.user_metadata.full_name ?? user.user_metadata.name ?? email }
}

// Fake login, used only when Supabase is not configured.
let mockUser: User | null = null
const mockListeners = new Set<(user: User | null) => void>()

function setMockUser(user: User | null) {
  mockUser = user
  for (const listener of mockListeners) listener(user)
}

// Calls back with the current user once the session is restored, then on every change.
// Returns the unsubscribe function.
export function onUserChange(callback: (user: User | null) => void): () => void {
  if (supabase) {
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      callback(session ? toUser(session.user) : null)
    })
    return () => data.subscription.unsubscribe()
  }
  mockListeners.add(callback)
  callback(mockUser)
  return () => {
    mockListeners.delete(callback)
  }
}

// Stand-in token for the fake login. MockApiClient never reads it.
const MOCK_ACCESS_TOKEN = 'mock-access-token'

// The signed-in user's access token (a Supabase JWT) for `Authorization: Bearer`,
// or null when logged out. Ask for it on each request instead of keeping a copy:
// Supabase rotates it about every hour, and getSession refreshes an expired one.
export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return mockUser ? MOCK_ACCESS_TOKEN : null
  const { data, error } = await supabase.auth.getSession()
  if (error) throw error
  return data.session?.access_token ?? null
}

// Real sign-in leaves the page for Google and comes back to this URL, so anything
// that must survive it (a pending incident) has to be in sessionStorage first.
export async function signInWithGoogle() {
  if (!supabase) {
    await new Promise((resolve) => setTimeout(resolve, 400))
    setMockUser({ email: 'student@example.com', name: 'Test Student' })
    return
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin + window.location.pathname },
  })
  if (error) throw error
}

// Local scope: log out this browser only. The default ('global') would also end
// the session on every other device signed in to the same account.
export async function signOut() {
  if (!supabase) {
    setMockUser(null)
    return
  }
  const { error } = await supabase.auth.signOut({ scope: 'local' })
  if (error) throw error
}

// If Google or Supabase sent the user back with an error (for example they
// cancelled), read it once and strip it from the address bar.
function takeRedirectError(): string | null {
  const url = new URL(window.location.href)
  const hash = new URLSearchParams(url.hash.slice(1))
  const code = url.searchParams.get('error') ?? hash.get('error')
  const description = url.searchParams.get('error_description') ?? hash.get('error_description')
  if (!code && !description) return null
  for (const key of ['error', 'error_code', 'error_description']) url.searchParams.delete(key)
  if (hash.has('error') || hash.has('error_description')) url.hash = ''
  window.history.replaceState(window.history.state, '', url.toString())
  return code === 'access_denied' ? 'Google sign-in was cancelled.' : `Sign-in failed: ${description ?? code}`
}

export const redirectError = supabase ? takeRedirectError() : null
