import { Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ProjectEditor from './pages/ProjectEditor'
import PageShell from './components/layout/PageShell'

function App() {
  return (
    <PageShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/project/:projectId" element={<ProjectEditor />} />
      </Routes>
    </PageShell>
  )
}

export default App
