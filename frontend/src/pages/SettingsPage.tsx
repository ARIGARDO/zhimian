import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

const labels = { configured: '配置已填写', missing: '尚未配置', invalid_url: '服务地址格式无效' }

export function SettingsPage() {
  const status = useQuery({ queryKey: ['model-configuration'], queryFn: api.modelConfiguration, retry: false })
  return <><div className="page-head"><div className="eyebrow">LOCAL CONFIGURATION</div><h1>模型配置</h1><p>密钥只保存在本机服务端，不在网页中输入或显示。配置检查不会连接模型供应商。</p></div>
    {status.isError && <div className="alert error">无法读取服务配置，请确认服务已启动。<button onClick={() => void status.refetch()}>重试</button></div>}
    {status.isPending && <div className="surface-card empty-state">正在读取配置状态...</div>}
    {status.data && <div className="two-grid"><section className="surface-card interview-section"><h2>聊天与面试模型</h2><p>{labels[status.data.chat]} · 用于问答、追问和复盘</p><p>在项目根目录的 <code>.env</code> 中填写 <code>MODEL_BASE_URL</code>、<code>MODEL_NAME</code> 和 <code>MODEL_API_KEY</code>。</p></section>
      <section className="surface-card interview-section"><h2>知识检索 Embedding</h2><p>{labels[status.data.embedding]} · 需要 {status.data.embedding_dimensions} 维向量</p><p>可选填写 <code>EMBEDDING_BASE_URL</code>、<code>EMBEDDING_MODEL</code> 和 <code>EMBEDDING_API_KEY</code>。未配置或出错时使用关键词检索。</p></section></div>}
    <section className="surface-card interview-section section"><h2>首次配置步骤</h2><ol><li>复制项目根目录的 <code>.env.example</code> 为 <code>.env</code>，填写自己的供应商地址、模型名与密钥。</li><li>在项目目录运行 <code>docker compose up -d --force-recreate backend</code>，让配置生效；然后刷新此页。</li><li>使用向量检索前，确认供应商支持 384 维并了解费用，再运行 <code>docker compose run --rm backend python -m app.tools.index_knowledge</code>。</li></ol><p>状态仅表示字段和地址格式完整，不代表密钥有效、供应商可用或模型质量已验证。建立向量索引和发送问题会调用供应商并可能产生费用。</p><p>正式题库需人工审核和单独启用；操作步骤见仓库 README。</p><Link className="app-button app-button-outline" to="/interviews/new">配置模拟面试</Link></section>
  </>
}
