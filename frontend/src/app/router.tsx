import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from '../components/layout/AppLayout'
import { HomePage } from '../pages/HomePage'
import { LearnCatalogPage } from '../pages/LearnCatalogPage'
import { TopicPage } from '../pages/TopicPage'
import { ComingSoonPage } from '../pages/ComingSoonPage'

export function AppRouter() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<AppLayout />}>
      <Route index element={<HomePage />} />
      <Route path="learn" element={<LearnCatalogPage />} />
      <Route path="learn/topics/:topicId" element={<TopicPage />} />
      {['assistant','interviews','interviews/new','knowledge','tasks','growth','settings','*'].map(path =>
        <Route key={path} path={path} element={<ComingSoonPage />} />)}
    </Route>
  </Routes></BrowserRouter>
}
