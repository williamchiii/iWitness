import { useState } from 'react'

function App() {
  const [status, setStatus] = useState('')

  async function checkHealth() {
    try {
      const res = await fetch('/api/health', { method: 'POST' })
      setStatus(JSON.stringify(await res.json()))
    } catch {
      setStatus('unreachable')
    }
  }

  return (
    <>
      <h1>iWitness</h1>
      <button onClick={checkHealth}>Check health</button>
      <p>{status}</p>
    </>
  )
}

export default App
