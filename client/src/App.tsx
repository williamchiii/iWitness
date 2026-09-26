import { BrowserRouter, Route, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage'
import SavedIncidentsPage from './pages/SavedIncidentsPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/saved" element={<SavedIncidentsPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
