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
    <div className="flex h-full flex-col">
      <Header user={user} onLogIn={() => setShowSignIn(true)} onLogOut={() => setUser(null)} />
      <main className="flex min-h-0 flex-1 flex-col md:grid md:grid-cols-2 md:grid-rows-[minmax(0,1fr)]">
        <section className="min-h-0 overflow-y-auto px-6 py-8">
          <h1 className="text-3xl font-medium tracking-tight">Cameras</h1>
          <p className="mt-1 text-muted">I-95, Miami-Dade</p>
          <div className="mt-6">
            <CameraList cameras={cameras} activeId={activeId} onHover={setHoveredId} onSelect={setSelectedId} />
          </div>
        </section>
        <section className="h-[50vh] border-t border-line md:h-auto md:border-l md:border-t-0">
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
