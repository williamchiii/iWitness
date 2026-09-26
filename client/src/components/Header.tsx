import type { User } from '../lib/mock'

interface Props {
  user: User | null
  onLogIn: () => void
  onLogOut: () => void
}

// Floating pill centred over the map; the blurred tiles behind it are what frosts it.
// The bar itself ignores pointer events so the map stays draggable either side of the pill.
export default function Header({ user, onLogIn, onLogOut }: Props) {
  // On desktop the bar is inset past the camera pane (36rem pane + 1.5rem inset + 1.5rem gap),
  // so the pill centres in the strip of map the pane leaves uncovered.
  return (
    <header className="pointer-events-none absolute inset-x-0 top-4 z-20 flex justify-center px-4 md:top-6 md:pl-[39rem] md:pr-6">
      {/* Tracks the viewport up to max-w-5xl, so the pill stays proportional instead of hugging its content. */}
      <nav className="glass-pill pointer-events-auto flex w-full max-w-lg items-center justify-between gap-4 rounded-full border border-white/60 p-2">
        <span className="shrink-0 pl-3 text-lg font-semibold tracking-tight">iWitness</span>
        <div className="flex min-w-0 items-center gap-3">
          {user ? (
            <>
              <span className="hidden max-w-56 truncate text-sm text-muted sm:block">{user.email}</span>
              <button
                type="button"
                onClick={onLogOut}
                className="shrink-0 rounded-full border border-ink/15 px-5 py-2 text-sm font-medium transition-colors hover:bg-white/70"
              >
                Log out
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onLogIn}
              className="shrink-0 rounded-full bg-ink px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-black"
            >
              Log in
            </button>
          )}
        </div>
      </nav>
    </header>
  )
}
