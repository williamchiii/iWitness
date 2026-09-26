import type { User } from '../lib/mock'

interface Props {
  user: User | null
  onLogIn: () => void
  onLogOut: () => void
}

export default function Header({ user, onLogIn, onLogOut }: Props) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-line px-6">
      <span className="text-lg font-semibold tracking-tight">iWitness</span>
      {user ? (
        <div className="flex items-center gap-4">
          <span className="text-sm text-muted">{user.email}</span>
          <button
            type="button"
            onClick={onLogOut}
            className="rounded-md border border-line px-4 py-2 text-sm font-medium transition-colors hover:bg-surface"
          >
            Log out
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onLogIn}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-black"
        >
          Log in
        </button>
      )}
    </header>
  )
}
