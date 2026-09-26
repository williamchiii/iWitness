import { useEffect, useState } from 'react'
import CameraList from '../components/CameraList'
import CameraMap from '../components/CameraMap'
import CameraModal from '../components/CameraModal'
import Header from '../components/Header'
import SignInDialog from '../components/SignInDialog'
import { cameras } from '../lib/cameras'
import { onUserChange, redirectError, signInWithGoogle, signOut } from '../lib/auth'
import type { User } from '../lib/auth'
import { clearPendingIncident, readPendingIncident } from '../lib/pendingIncident'

export default function HomePage() {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  // An incident pressed before the Google redirect (or a reload) reopens its camera.
  const [selectedId, setSelectedId] = useState<string | null>(() => readPendingIncident()?.cameraId ?? null)
  const [user, setUser] = useState<User | null>(null)
  const [showSignIn, setShowSignIn] = useState(false)
  const [notice, setNotice] = useState<string | null>(redirectError)

  useEffect(
    () =>
      onUserChange((next) => {
        setUser(next)
        if (next) setShowSignIn(false)
      }),
    [],
  )

  function closeCamera() {
    setSelectedId(null)
    clearPendingIncident()
  }

  const selectedIndex = cameras.findIndex((c) => c.id === selectedId)
  const selected = selectedIndex >= 0 ? cameras[selectedIndex] : undefined
  const activeId = hoveredId ?? selectedId

  return (
    <div className="relative h-full">
      <Header
        user={user}
        onLogIn={() => setShowSignIn(true)}
        onLogOut={() => signOut().catch(() => setNotice('Could not log out. Check your connection and try again.'))}
      />
      <main className="flex h-full min-h-0 flex-col">
        {/* Desktop: the list floats over a full-bleed map. Mobile: they stack. */}
        <section className="glass-pane z-10 min-h-0 overflow-y-auto px-6 pb-8 pt-24 md:absolute md:inset-y-6 md:left-6 md:w-[36rem] md:rounded-2xl md:border md:border-white/60 md:pb-6 md:pt-6">
          <h1 className="text-3xl font-medium tracking-tight">Cameras</h1>
          <div className="mt-6">
            <CameraList cameras={cameras} activeId={activeId} onHover={setHoveredId} onSelect={setSelectedId} />
          </div>
        </section>
        {/* z-0 seals Leaflet's internal z-indexes (panes 400, controls 1000) into their own stacking context. */}
        <section className="relative z-0 h-[50vh] border-t border-line md:absolute md:inset-0 md:h-auto md:border-t-0">
          <CameraMap
            cameras={cameras}
            activeId={activeId}
            selected={selected}
            onHover={setHoveredId}
            onSelect={setSelectedId}
          />
        </section>
      </main>
      {selected && (
        <CameraModal
          key={selected.id}
          camera={selected}
          number={selectedIndex + 1}
          signedIn={user !== null}
          onSignIn={signInWithGoogle}
          onClose={closeCamera}
        />
      )}
      {notice && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-[2500] flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center justify-between gap-4 rounded-lg border border-line bg-white px-4 py-3 text-sm shadow-lg"
        >
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} className="shrink-0 text-muted hover:text-ink">
            Dismiss
          </button>
        </div>
      )}
      {showSignIn && <SignInDialog onSignIn={signInWithGoogle} onClose={() => setShowSignIn(false)} />}
    </div>
  )
}
