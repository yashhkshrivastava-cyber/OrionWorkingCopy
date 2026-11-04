import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider } from './components/ui/Toast'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { HomeSwitch } from './pages/HomeSwitch'
import { LoginPage } from './pages/LoginPage'
import { lazyPage } from './lazyPage'

const ResetPasswordPage = lazyPage(() => import('./pages/ResetPasswordPage'), 'ResetPasswordPage')
const SettingsPage = lazyPage(() => import('./pages/SettingsPage'), 'SettingsPage')

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route element={<Layout />}>
              <Route path="/" element={<HomeSwitch />} />
              <Route element={<ProtectedRoute />}>
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/dashboard/*" element={<></>} />
                <Route path="/data/*" element={<></>} />
                <Route path="/utility/*" element={<></>} />
                <Route path="/letterhead/*" element={<></>} />
                <Route path="/pdf-tools/*" element={<></>} />
                <Route path="/documents/*" element={<></>} />
                <Route path="/bank/*" element={<></>} />
                <Route path="/tenders/*" element={<></>} />
                <Route path="/attendance/*" element={<></>} />
                <Route path="/etl/*" element={<></>} />
                <Route path="/sql/*" element={<></>} />
                <Route path="/admin/*" element={<></>} />
                <Route path="/messages/*" element={<></>} />
                <Route path="/tasks/*" element={<></>} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  )
}
