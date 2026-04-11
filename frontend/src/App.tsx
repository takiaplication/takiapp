import { Routes, Route } from 'react-router-dom'
import KanbanDashboard from './pages/KanbanDashboard'
import ProjectEditor from './pages/ProjectEditor'
import LibraryPage from './pages/LibraryPage'
import PageShell from './components/layout/PageShell'

function App() {
  return (
    <PageShell>
      <Routes>
        <Route path="/" element={<KanbanDashboard />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/project/:projectId" element={<ProjectEditor />} />
      </Routes>
    </PageShell>
  )
}

export default App
