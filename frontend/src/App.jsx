import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Workspace from './pages/Workspace.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="login" element={<Login />} />

        <Route element={<ProtectedRoute />}>
          <Route index element={<Navigate to="/workspaces" replace />} />
          <Route path="workspaces" element={<Dashboard />} />
          <Route path="workspaces/:id" element={<Workspace />} />
        </Route>

        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
