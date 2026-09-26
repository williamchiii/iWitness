import { useState } from 'react'
import CameraList from '../components/CameraList'
import CameraMap from '../components/CameraMap'
import CameraModal from '../components/CameraModal'
import Header from '../components/Header'
import SignInDialog from '../components/SignInDialog'
import { cameras } from '../lib/cameras'
import { signInWithGoogle } from '../lib/mock'
import type { User } from '../lib/mock'

export default function HomePage() {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [showSignIn, setShowSignIn] = useState(false)

  async function signIn() {
    setUser(await signInWithGoogle())
  }

  const selectedIndex = cameras.findIndex((c) => c.id === selectedId)
  const selected = selectedIndex >= 0 ? cameras[selectedIndex] : undefined
  const activeId = hoveredId ?? selectedId

  return (
    <div className="relative h-full">
      <Header user={user} onLogIn={() => setShowSignIn(true)} onLogOut={() => setUser(null)} />
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
          onSignIn={signIn}
          onClose={() => setSelectedId(null)}
        />
      )}
      {showSignIn && <SignInDialog onSignIn={signIn} onClose={() => setShowSignIn(false)} />}
    </div>
  )
}
