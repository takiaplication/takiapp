import { Routes, Route } from 'react-router-dom'
import KanbanDashboard from './pages/KanbanDashboard'
import ProjectEditor from './pages/ProjectEditor'
import PageShell from './components/layout/PageShell'

function App() {
  return (
    <PageShell>
      <Routes>
        <Route path="/" element={<KanbanDashboard />} />
        <Route path="/project/:projectId" element={<ProjectEditor />} />
      </Routes>
    </PageShell>
  )
}

export default App
