import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BookOpen, BrainCircuit, CalendarDays, ChartNoAxesCombined, FileText, Home,
  LibraryBig, Menu, MessageCircle, Mic, Settings2,
} from 'lucide-react'
import { useUIStore } from '../../app/ui-store'

const nav = [
  { to: '/', label: '概览', icon: Home, end: true },
  { to: '/learn', label: '智能学习', icon: BookOpen },
  { to: '/assistant', label: 'AI 问答助手', icon: MessageCircle },
  { to: '/interviews/new', label: '模拟面试', icon: Mic },
  { to: '/interviews', label: '面试记录', icon: FileText },
  { to: '/tasks', label: '学习任务', icon: CalendarDays },
  { to: '/growth', label: '个人成长', icon: ChartNoAxesCombined },
  { to: '/knowledge', label: '知识库', icon: LibraryBig },
]

export function AppLayout() {
  const mobileNavOpen = useUIStore((s) => s.mobileNavOpen)
  const setMobileNavOpen = useUIStore((s) => s.setMobileNavOpen)
  const location = useLocation()
  const selected = nav.find((item) => item.end ? location.pathname === item.to : location.pathname.startsWith(item.to))
  return <div className="shell">
    {mobileNavOpen && <button className="mobile-screen" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} />}
    <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`}>
      <NavLink to="/" className="brand" onClick={() => setMobileNavOpen(false)}>
        <span className="brand-mark">知</span>
        <span><strong>知面</strong><small>LEARN · INTERVIEW</small></span>
      </NavLink>
      <div className="side-caption">WORKSPACE</div>
      <nav aria-label="主导航">
        {nav.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileNavOpen(false)} className={({ isActive }) => `side-link ${isActive ? 'active' : ''}`}>
          <Icon size={19} strokeWidth={1.8} /> {label}
        </NavLink>)}
      </nav>
      <div className="side-footer">
        <div className="deployment-note"><strong>M1 · 开发里程碑</strong><p>课程目录、专题阅读与进度真实持久化。其余模块将分阶段接入。</p></div>
        <NavLink className="side-link" to="/settings" onClick={() => setMobileNavOpen(false)}><Settings2 size={18}/> 系统配置</NavLink>
      </div>
    </aside>
    <div className="main-area">
      <header className="topbar">
        <div className="crumb"><button className="mobile-menu" aria-label="打开导航" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>工作台 / <strong>{selected?.label ?? '系统配置'}</strong></div>
        <div className="top-actions"><span className="status-tag"><span className="dot"/>M1 · 实际 API</span><span className="desktop-only">单实例 · 无平台账号</span><BrainCircuit size={17} color="#6f889c" /></div>
      </header>
      <main className="page-content"><Outlet /></main>
    </div>
  </div>
}
