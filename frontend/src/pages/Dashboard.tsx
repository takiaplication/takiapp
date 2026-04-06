import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProjectStore } from '../store/projectStore'

export default function Dashboard() {
  const { projects, fetchProjects, createProject, removeProject } = useProjectStore()
  const [newName, setNewName] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const handleCreate = async () => {
    if (!newName.trim()) return
    const project = await createProject(newName.trim())
    setNewName('')
    navigate(`/project/${project.id}`)
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h2 className="text-2xl font-bold mb-6">Projects</h2>

      {/* Create new project */}
      <div className="flex gap-3 mb-8">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          placeholder="New project name..."
          className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors"
        />
        <button
          onClick={handleCreate}
          className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          Create Project
        </button>
      </div>

      {/* Project list */}
      {projects.length === 0 ? (
        <div className="text-center py-16 text-zinc-500">
          <p className="text-lg">No projects yet</p>
          <p className="text-sm mt-1">Create your first project to get started</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {projects.map((project) => (
            <div
              key={project.id}
              className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex items-center justify-between hover:border-zinc-700 transition-colors cursor-pointer"
              onClick={() => navigate(`/project/${project.id}`)}
            >
              <div>
                <h3 className="font-medium">{project.name}</h3>
                <p className="text-sm text-zinc-500 mt-0.5">
                  {project.status} &middot; {new Date(project.created_at).toLocaleDateString()}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  removeProject(project.id)
                }}
                className="text-zinc-500 hover:text-red-400 text-sm transition-colors px-3 py-1"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
