import { BrowserRouter, Route, Routes, useParams } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { HomePage } from '../pages/HomePage'
import { LearnCatalogPage } from '../pages/LearnCatalogPage'
import { TopicPage } from '../pages/TopicPage'
import { ChatPage } from '../pages/ChatPage'
import { ComingSoonPage } from '../pages/ComingSoonPage'
import { TasksPage } from '../pages/TasksPage'
import { GrowthPage } from '../pages/GrowthPage'
import { SettingsPage } from '../pages/SettingsPage'
const InterviewConfigPage = lazy(() => import('../pages/InterviewPage').then(m => ({ default: m.InterviewConfigPage })))
const InterviewHistoryPage = lazy(() => import('../pages/InterviewPage').then(m => ({ default: m.InterviewHistoryPage })))
const InterviewSessionPage = lazy(() => import('../pages/InterviewPage').then(m => ({ default: m.InterviewSessionPage })))
const InterviewReportPage = lazy(() => import('../pages/InterviewPage').then(m => ({ default: m.InterviewReportPage })))

function TopicChat() {
  const { topicId } = useParams()
  return <ChatPage key={topicId} topicId={topicId} />
}

export function AppRouter() {
  return <BrowserRouter><Suspense fallback={<div className="empty-state">正在加载页面...</div>}><Routes>
    <Route path="/" element={<AppLayout />}>
      <Route index element={<HomePage />} />
      <Route path="learn" element={<LearnCatalogPage />} />
      <Route path="learn/topics/:topicId" element={<TopicPage />} />
      <Route path="learn/topics/:topicId/chat/:conversationId?" element={<TopicChat />} />
      <Route path="assistant/:conversationId?" element={<ChatPage />} />
      <Route path="interviews" element={<InterviewHistoryPage />} />
      <Route path="interviews/new" element={<InterviewConfigPage />} />
      <Route path="interviews/:interviewId" element={<InterviewSessionPage />} />
      <Route path="interviews/:interviewId/report" element={<InterviewReportPage />} />
      <Route path="tasks" element={<TasksPage />} />
      <Route path="knowledge" element={<LearnCatalogPage />} />
      <Route path="growth" element={<GrowthPage />} />
      <Route path="settings" element={<SettingsPage />} />
      {['*'].map(path =>
        <Route key={path} path={path} element={<ComingSoonPage />} />)}
    </Route>
  </Routes></Suspense></BrowserRouter>
}
