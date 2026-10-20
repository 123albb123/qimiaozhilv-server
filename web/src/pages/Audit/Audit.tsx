import { useQuery } from '@tanstack/react-query'
import { ClipboardList, ScrollText, Search, TerminalSquare } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, AuditRecord, CommandRecord } from '../../api/client'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, StatusPill } from '../../components/Ui'

function time(value: string) {
  const date = new Date(Number(value) * 1000)
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function Audit() {
  const [tab, setTab] = useState<'audit' | 'commands'>('audit')
  const [filter, setFilter] = useState('')
  const [search, setSearch] = useState(''); const [result, setResult] = useState(''); const [pages, setPages] = useState([''])
  const cursor = pages[pages.length - 1]
  useEffect(() => { setPages(['']) }, [tab, search, result])
  const audit = useQuery({ queryKey: ['audit', cursor, search, result], queryFn: () => api.audit(cursor, search, result), enabled: tab === 'audit' })
  const commands = useQuery({ queryKey: ['commands', cursor, search, result], queryFn: () => api.commands(cursor, search, result), enabled: tab === 'commands' })
  const current = tab === 'audit' ? audit : commands
  const auditItems = audit.data?.items || []
  const commandItems = commands.data?.items || []

  return <>
    <PageHeader eyebrow="CONTROL PLANE / TRACE" title="审计与命令" description="每次副作用操作都可追踪，命令结果保留请求 ID" />
    <form className="toolbar" onSubmit={e => { e.preventDefault(); setSearch(filter.trim()) }}><div className="search"><Search size={16} /><input className="input" value={filter} onChange={e => setFilter(e.target.value)} placeholder="搜索动作、目标、管理员 ID 或请求 ID" /></div><select className="select" aria-label="执行结果" value={result} onChange={e => setResult(e.target.value)}><option value="">全部结果</option>{['completed', 'rejected', 'pending', 'accepted'].map(status => <option key={status} value={status}>{status}</option>)}</select><Button type="submit">查询</Button></form>
    <div className="tabs" style={{ marginBottom: 16 }}><button className={tab === 'audit' ? 'tab active' : 'tab'} onClick={() => setTab('audit')}><ClipboardList size={14} />审计日志</button><button className={tab === 'commands' ? 'tab active' : 'tab'} onClick={() => setTab('commands')}><TerminalSquare size={14} />控制命令</button></div>
    <Card><div className="section-title"><h2><ScrollText size={15} style={{ verticalAlign: 'middle', marginRight: 7 }} />{tab === 'audit' ? '操作审计' : '命令记录'}</h2><span>{current.data ? `${current.data.items.length} 条记录` : '读取中'}</span></div>
      {current.isLoading ? <LoadingState /> : current.isError ? <ErrorState message={current.error instanceof Error ? current.error.message : undefined} onRetry={() => current.refetch()} /> : tab === 'audit' ? <AuditTable items={auditItems} /> : <CommandTable items={commandItems} />}
      <div className="pagination"><Button variant="secondary" disabled={pages.length === 1 || current.isFetching} onClick={() => setPages(p => p.slice(0, -1))}>上一页</Button><span>第 {pages.length} 页 · 每页最多 50 条</span><Button variant="secondary" disabled={!current.data?.nextCursor || current.isFetching} onClick={() => current.data?.nextCursor && setPages(p => [...p, current.data!.nextCursor])}>下一页</Button></div>
    </Card>
  </>
}

function AuditTable({ items }: { items: AuditRecord[] }) {
  if (!items.length) return <EmptyState />
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>时间</th><th>动作</th><th>目标</th><th>结果</th><th>请求 ID</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td className="mono muted">{time(item.createdAt)}</td><td className="mono">{item.action}</td><td>{item.targetType} <span className="muted mono">{item.targetId}</span></td><td><StatusPill status={item.result}>{item.result}</StatusPill></td><td className="mono muted" style={{ fontSize: 10 }}>{item.requestId.slice(0, 16)}…</td></tr>)}</tbody></table></div>
}

function CommandTable({ items }: { items: CommandRecord[] }) {
  if (!items.length) return <EmptyState />
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>创建时间</th><th>动作</th><th>目标角色</th><th>状态</th><th>请求 ID</th></tr></thead><tbody>{items.map(item => <tr key={item.requestId}><td className="mono muted">{time(item.createdAt)}</td><td className="mono">{item.action}</td><td className="mono">{item.targetId}</td><td><StatusPill status={item.status}>{item.status}</StatusPill></td><td className="mono muted" style={{ fontSize: 10 }}>{item.requestId}</td></tr>)}</tbody></table></div>
}
