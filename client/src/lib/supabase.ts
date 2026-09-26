import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

// Null when client/.env.local has no Supabase settings; lib/auth then fakes the login.
// PKCE: Google sends back a one-time ?code= that supabase-js swaps for a session on load.
export const supabase = url && key ? createClient(url, key, { auth: { flowType: 'pkce' } }) : null
