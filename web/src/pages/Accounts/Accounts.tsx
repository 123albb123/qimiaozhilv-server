import { useQuery } from '@tanstack/react-query'
import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../../components/Ui'

export function Accounts() {
  const [input, setInput] = useState(''); const [query, setQuery] = useState(''); const [pages, setPages] = useState([''])
  const cursor = pages[pages.length - 1]
  const data = useQuery({ queryKey: ['accounts', query, cursor], queryFn: () => api.accounts({ query, cursor }) })
  const submit = (e: FormEvent) => { e.preventDefault(); setQuery(input.trim()); setPages(['']) }
  return <><PageHeader title="游戏账号" description="按账号 ID 或用户名查询，查看注册信息及关联角色" />
    <form className="toolbar" onSubmit={submit}><input aria-label="账号 ID 或用户名" className="input" value={input} onChange={e => setInput(e.target.value)} placeholder="账号 ID 或用户名" /><Button type="submit">查询</Button></form>
    <Card>{data.isLoading ? <LoadingState /> : data.isError ? <ErrorState message={data.error.message} onRetry={() => data.refetch()} /> : !data.data?.items.length ? <EmptyState message="没有匹配账号" /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>账号 ID</th><th>用户名</th><th>注册时间</th><th>角色数</th><th /></tr></thead><tbody>{data.data.items.map(account => <tr key={account.id}><td>{account.id}</td><td>{account.account}</td><td>{Number(account.createdAt) ? new Date(Number(account.createdAt) * 1000).toLocaleString('zh-CN') : '暂无数据'}</td><td>{account.playerCount}</td><td><Link className="btn btn-ghost" to={`/players?account=${encodeURIComponent(account.account)}`}>查看角色</Link></td></tr>)}</tbody></table></div>}
    <div className="pagination"><Button variant="secondary" disabled={pages.length === 1 || data.isFetching} onClick={() => setPages(p => p.slice(0, -1))}>上一页</Button><span>第 {pages.length} 页</span><Button variant="secondary" disabled={!data.data?.nextCursor || data.isFetching} onClick={() => data.data?.nextCursor && setPages(p => [...p, data.data!.nextCursor])}>下一页</Button></div></Card></>
}
