import { useState, useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { authApi } from './api/client'

// Pages
import Login from './pages/Login'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Records from './pages/Records'
import ProductKnowledge from './pages/ProductKnowledge'
import EvaluationCriteria from './pages/EvaluationCriteria'
import EmailTemplates from './pages/EmailTemplates'

function App() {
  const [loading, setLoading] = useState(true)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    // Check auth status on mount
    const checkAuth = async () => {
      if (location.pathname === '/login') {
        setLoading(false)
        return
      }

      try {
        await authApi.me()
        setIsAuthenticated(true)
      } catch {
        setIsAuthenticated(false)
        navigate('/login')
      } finally {
        setLoading(false)
      }
    }

    checkAuth()
  }, [navigate, location.pathname])

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={
        isAuthenticated ? <Navigate to="/" replace /> : <Login onLogin={() => setIsAuthenticated(true)} />
      } />
      <Route path="/" element={
        isAuthenticated ? <Layout onLogout={() => setIsAuthenticated(false)} /> : <Navigate to="/login" replace />
      }>
        <Route index element={<Dashboard />} />
        <Route path="records" element={<Records />} />
        <Route path="product-knowledge" element={<ProductKnowledge />} />
        <Route path="evaluation-criteria" element={<EvaluationCriteria />} />
        <Route path="email-templates" element={<EmailTemplates />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App