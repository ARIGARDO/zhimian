import { ArrowLeft, Construction, ShieldAlert } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

const labels: Record<string, { title: string; stage: string; desc: string }> = {
  '/assistant': { title: 'AI 问答助手', stage: 'M2', desc: '打开即提问、首次发送自动创建会话、历史记录与流式输出。' },
  '/interviews/new': { title: '模拟面试', stage: 'M3', desc: '岗位/JD 设置、练习与正式模式、动态追问和中断处理。' },
  '/interviews': { title: '面试记录', stage: 'M3', desc: '完整/未完成场次分离，支持逐题复盘。' },
  '/knowledge': { title: '知识库', stage: 'M4', desc: '公共知识库与外部知识库上下布局，文档上传和 RAG 检索。' },
  '/tasks': { title: '学习任务', stage: 'M5', desc: '用户主动确认的推荐任务，待完成/进行中/已完成三态。' },
  '/growth': { title: '个人成长', stage: 'M5', desc: '学习进度、知识掌握、最近面试和学习任务四项概览。' },
  '/settings': { title: 'API 设置', stage: 'M2', desc: '模型 API Key 仅由服务端安全配置，前端不直接持有长期密钥。' },
}
export function ComingSoonPage() {
  const pathname = useLocation().pathname
  const info = labels[pathname] ?? { title: '页面不存在', stage: '—', desc: '请从主导航选择一个页面。' }
  return <><div className="page-head"><div className="eyebrow">UPCOMING MILESTONE</div><h1>{info.title}</h1><p>{info.desc}</p></div>
    <div className="surface-card future-card"><Construction size={36}/><span className="pill blue">{info.stage} 计划实现</span><h2>功能尚未接入</h2><p>当前是实际可运行的 M1 工程。这里不使用假聊天、假面试报告或虚构知识库结果冒充完成的功能。</p>
      <div className="alert info"><ShieldAlert size={17}/><span>本项目默认面向个人/可信环境。公开部署之前需要补齐访问保护、HTTPS 和模型调用限额。</span></div>
      <Link className="app-button app-button-primary" to="/learn"><ArrowLeft size={16}/> 先体验智能学习</Link>
    </div>
  </>
}
