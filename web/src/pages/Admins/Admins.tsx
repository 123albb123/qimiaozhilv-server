import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useState } from 'react'
import { AdminInput, AdminUser, api } from '../../api/client'
import { Button, Card, EmptyState, ErrorState, Field, LoadingState, PageHeader } from '../../components/Ui'
import { useAuth } from '../../layouts/Shell'

const empty = (): AdminInput => ({ username: '', displayName: '', password: '', roles: ['readonly'], active: true, reason: '' })

export function Admins() {
  const admins = useQuery({ queryKey: ['admins'], queryFn: api.admins }); const roles = useQuery({ queryKey: ['admin-roles'], queryFn: api.adminRoles })
  const [id, setId] = useState(''); const [form, setForm] = useState<AdminInput>(empty); const [notice, setNotice] = useState(''); const [error, setError] = useState('')
  const session = useAuth(); const cache = useQueryClient()
  const save = useMutation({ mutationFn: () => api.saveAdmin(id, form), onSuccess: () => { setNotice('管理员已保存，目标管理员的旧会话已失效'); setError(''); setId(''); setForm(empty()); void cache.invalidateQueries({ queryKey: ['admins'] }) }, onError: e => setError(e instanceof Error ? e.message : '保存失败') })
  const edit = (admin: AdminUser) => { setId(admin.id); setForm({ username: admin.username, displayName: admin.displayName, password: '', roles: admin.roles, active: admin.active, reason: '' }); setError(''); setNotice('') }
  const submit = (e: FormEvent) => { e.preventDefault(); setNotice(''); setError(''); if (save.isPending) return; if (!window.confirm(`确认${id ? '修改' : '创建'}管理员 ${form.username}？${id ? '该管理员所有旧会话将失效。' : ''}`)) return; save.mutate() }
  return <><PageHeader title="管理员与权限" description="使用既有角色权限。子 GM 的游戏账号绑定在“子 GM”页面管理" />
    <Card>{admins.isLoading ? <LoadingState /> : admins.isError ? <ErrorState message={admins.error.message} onRetry={() => admins.refetch()} /> : !admins.data?.items.length ? <EmptyState /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>登录名</th><th>显示名称</th><th>角色</th><th>状态</th><th /></tr></thead><tbody>{admins.data.items.map(admin => <tr key={admin.id}><td>{admin.username}</td><td>{admin.displayName || '—'}</td><td>{admin.roles.map(role => roles.data?.items.find(r => r.name === role)?.description || role).join('、')}</td><td>{admin.active ? '启用' : '停用'}</td><td><Button variant="ghost" disabled={admin.id === session?.adminId} onClick={() => edit(admin)}>编辑</Button></td></tr>)}</tbody></table></div>}</Card>
    <Card style={{ marginTop: 16 }}><div className="section-title"><h2>{id ? `修改 ${form.username}` : '创建管理员'}</h2>{id ? <Button variant="ghost" onClick={() => { setId(''); setForm(empty()) }}>取消编辑</Button> : null}</div>
      <form className="card-pad" onSubmit={submit}><div className="field-row"><Field label="登录名"><input className="input" value={form.username} disabled={!!id} onChange={e => setForm({ ...form, username: e.target.value })} pattern="[A-Za-z0-9_.-]{3,64}" required /></Field><Field label="显示名称"><input className="input" value={form.displayName} onChange={e => setForm({ ...form, displayName: e.target.value })} /></Field></div>
      <Field label={id ? '新密码（留空保留原密码）' : '初始密码'}><input className="input" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} minLength={12} maxLength={72} autoComplete="new-password" required={!id} /></Field>
      <Field label="角色"><select className="select" value={form.roles[0] || ''} onChange={e => setForm({ ...form, roles: [e.target.value] })}>{roles.data?.items.map(role => <option key={role.name} value={role.name}>{role.description}</option>)}</select></Field>
      <Field label="状态"><select className="select" value={form.active ? '1' : '0'} onChange={e => setForm({ ...form, active: e.target.value === '1' })}><option value="1">启用</option><option value="0">停用</option></select></Field>
      <Field label="操作原因"><input className="input" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} maxLength={160} required /></Field>
      {error ? <div className="notice danger" role="alert">{error}</div> : null}{notice ? <div className="notice success" role="status">{notice}</div> : null}{roles.isError ? <ErrorState message="角色列表读取失败" onRetry={() => roles.refetch()} /> : null}
      <Button type="submit" loading={save.isPending} disabled={!roles.data} style={{ marginTop: 16 }}>保存管理员</Button></form>
    </Card></>
}
