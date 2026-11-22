import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from '../context/ToastContext.jsx'
import { DemoProvider } from '../context/DemoContext.jsx'
import AppLayout from '../components/layout/AppLayout.jsx'
import ConsolePage from '../pages/ConsolePage.jsx'
import ReviewPage from '../pages/ReviewPage.jsx'
import AuditLogPage from '../pages/AuditLogPage.jsx'
import NotFoundPage from '../pages/NotFoundPage.jsx'

/**
 * Routes
 *   /console         Console — Incident (live database + recovery composer)
 *   /console/review  Console — Review & approve (merge plan, conflict, patch)
 *   /audit-log       Audit log list (?q=&status=&scenario=&page=&recovery=)
 */
export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <DemoProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/console" replace />} />
              <Route path="console" element={<ConsolePage />} />
              <Route path="console/review" element={<ReviewPage />} />
              <Route path="audit-log" element={<AuditLogPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </DemoProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
