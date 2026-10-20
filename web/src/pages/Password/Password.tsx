import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, clearCsrfToken } from '../../api/client'
import { Button, Card, Field, PageHeader } from '../../components/Ui'

export function Password() {
  const [current, setCurrent] = useState(''); const [password, setPassword] = useState(''); const [repeat, setRepeat] = useState('')
  const [error, setError] = useState(''); const cache = useQueryClient(); const navigate = useNavigate()
  const change = useMutation({ mutationFn: () => api.changePassword(current, password), onSuccess: () => {
    clearCsrfToken(); cache.setQueryData(['me'], null); cache.removeQueries({ predicate: q => q.queryKey[0] !== 'me' }); navigate('/login', { replace: true })
  }, onError: e => setError(e instanceof Error ? e.message : '修改失败') })
  const submit = (e: FormEvent) => { e.preventDefault(); setError(''); if (password !== repeat) { setError('两次新密码不一致'); return }; if (new TextEncoder().encode(password).length < 12 || new TextEncoder().encode(password).length > 72) { setError('新密码长度须为 12-72 字节'); return }; change.mutate() }
  return <><PageHeader title="修改管理员密码" description="修改成功后，所有旧会话失效，请使用新密码重新登录" /><Card><form className="card-pad" onSubmit={submit} style={{ maxWidth: 520 }}>
    <Field label="当前密码"><input className="input" type="password" value={current} onChange={e => setCurrent(e.target.value)} autoComplete="current-password" required /></Field>
    <Field label="新密码" hint="建议使用至少 12 位字母和数字"><input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" minLength={12} maxLength={72} required /></Field>
    <Field label="再次输入新密码"><input className="input" type="password" value={repeat} onChange={e => setRepeat(e.target.value)} autoComplete="new-password" required /></Field>
    {error ? <div role="alert" className="notice danger">{error}</div> : null}<Button type="submit" loading={change.isPending} style={{ marginTop: 16 }}>修改并重新登录</Button>
  </form></Card></>
}
