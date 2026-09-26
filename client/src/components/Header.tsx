import type { User } from '../lib/auth'
import { OUTLINE_PILL } from '../lib/styles'

interface Props {
  user: User | null
  query: string
  onQueryChange: (query: string) => void
  // Enter in the search box: open the top match.
  onSearchSubmit: () => void
  onLogIn: () => void
  onLogOut: () => void
}

// Floating pill centred over the map; the blurred tiles behind it are what frosts it.
// The bar itself ignores pointer events so the map stays draggable either side of the pill.
export default function Header({ user, query, onQueryChange, onSearchSubmit, onLogIn, onLogOut }: Props) {
  // On desktop the bar is inset past the camera pane (36rem pane + 1.5rem inset + 1.5rem gap),
  // so the pill centres in the strip of map the pane leaves uncovered.
  return (
    <header className="pointer-events-none absolute inset-x-0 top-4 z-20 flex justify-center px-4 md:top-6 md:pl-[39rem] md:pr-6">
      {/* Tracks the viewport up to max-w-2xl, so the pill stays proportional instead of hugging its content. */}
      {/* On phones the search drops to its own row, so the pill becomes a rounded panel. */}
      <nav className="glass-pill pointer-events-auto flex w-full max-w-2xl flex-wrap items-center gap-2 rounded-3xl border border-white/60 p-2 sm:flex-nowrap sm:gap-3 sm:rounded-full">
        <span className="mr-auto shrink-0 pl-3 text-lg font-semibold tracking-tight sm:mr-0">iWitness</span>
        <label className="order-last flex min-w-0 basis-full items-center gap-2 rounded-full sm:order-none sm:flex-1 sm:basis-auto border border-ink/10 bg-white/50 px-3 py-2 text-sm text-muted transition-colors focus-within:border-ink/25 focus-within:bg-white/80">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="shrink-0">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                onSearchSubmit()
                e.currentTarget.blur()
              } else if (e.key === 'Escape') {
                onQueryChange('')
              }
            }}
            placeholder="Search cameras"
            aria-label="Search cameras"
            className="w-full min-w-0 bg-transparent text-ink outline-none placeholder:text-muted"
          />
        </label>
        <div className="flex shrink-0 items-center gap-2">
          {user ? (
            <>
              <span className="hidden max-w-32 truncate pr-1 text-sm text-muted lg:block">{user.name}</span>
              <button type="button" onClick={onLogOut} className={OUTLINE_PILL}>
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
