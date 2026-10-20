import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, StatusPill } from '../../components/Ui'

function number(value: string) { const n = Number(value); return !Number.isFinite(n) || n < 0 ? '暂无数据' : new Intl.NumberFormat('zh-CN').format(n) }
function time(value: string) { return Number(value) > 0 ? new Date(Number(value) * 1000).toLocaleString('zh-CN') : '暂无数据' }

export function Dashboard() {
  const query = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, refetchInterval: 30_000 })
  if (query.isLoading) return <><PageHeader title="运行总览" /><LoadingState /></>
  if (query.isError || !query.data) return <><PageHeader title="运行总览" /><ErrorState message={query.error instanceof Error ? query.error.message : undefined} onRetry={() => query.refetch()} /></>
  const data = query.data
  return <><PageHeader title="运行总览" description="来自游戏服务、MySQL、Redis 与审计记录的实时数据，每 30 秒刷新" action={<Button variant="secondary" onClick={() => query.refetch()}>刷新数据</Button>} />
    <div className="grid grid-4">{[['在线角色', data.online], ['角色总量', data.players], ['注册账号', data.accounts], ['24 小时内登录角色', data.recentLogins24h]].map(([label, value]) => <Card className="metric-card" key={label}><div className="metric-label">{label}</div><div className="metric-value">{number(value)}</div></Card>)}</div>
    <div className="grid grid-2" style={{ marginTop: 16 }}><Card><div className="section-title"><h2>依赖健康</h2><span>当前检测结果</span></div><div className="health-list">{([['MySQL 数据库', data.health.mysql], ['Redis', data.health.redis], ['游戏 TCP 服务', data.health.game]] as const).map(([label, dependency]) => <div className="health-row" key={label}><div><b>{label}</b><small>{dependency.detail || (dependency.status === 'up' ? '连接正常' : '状态暂无数据')}</small></div><div><span className="health-latency">{dependency.latencyMs || '—'} ms</span><StatusPill status={dependency.status}>{dependency.status === 'up' ? '正常' : '异常'}</StatusPill></div></div>)}</div></Card>
      <Card><div className="section-title"><h2>版本与连接</h2></div><div className="card-pad"><p>游戏地址：<span className="mono">{data.health.publicAddress || '暂无数据'}</span></p><p>服务版本：<span className="mono">{data.health.version || '暂无数据'}</span></p><p>配置版本：{Number(data.configRevision) > 0 ? data.configRevision : '暂无数据'}</p><p>管理 API 启动：{time(data.health.startedAt)}</p><p className="muted">暂无历史在线趋势数据。在线数取自当前 Redis 状态。</p></div></Card></div>
    <div className="grid grid-2" style={{ marginTop: 16 }}><Card><div className="section-title"><h2>最近登录</h2></div>{!data.recentLogins?.length ? <EmptyState message="暂无登录记录" /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>角色</th><th>最近登录</th></tr></thead><tbody>{data.recentLogins.map(player => <tr key={player.id}><td><Link className="link" to={`/players/${player.id}`}>{player.name || player.id}</Link></td><td>{time(player.lastLogin)}</td></tr>)}</tbody></table></div>}</Card>
      <Card><div className="section-title"><h2>最近 GM 操作</h2><Link className="link" to="/audit">查看记录</Link></div>{!data.recentAudit?.length ? <EmptyState message="暂无操作记录" /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>管理员 ID</th><th>操作</th><th>结果</th><th>时间</th></tr></thead><tbody>{data.recentAudit.map(audit => <tr key={audit.id}><td>{audit.adminId}</td><td>{audit.action}</td><td><StatusPill status={audit.result} /></td><td>{time(audit.createdAt)}</td></tr>)}</tbody></table></div>}</Card></div>
  </>
}
