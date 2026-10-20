import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, newIdempotencyKey } from '../../api/client'
import { Button, Card, Field, PageHeader, StatusPill } from '../../components/Ui'
import { ItemPicker, SelectedItem, itemSelectionError, itemSelectionPayload } from '../../components/ItemPicker'
import { can, useAuth } from '../../layouts/Shell'

type Mode = 'mail' | 'items/grant' | 'currency-adjust'
type Row = { id: string; name: string; key: string; status: string; message: string }
type Plan = { owner: string; mode: Mode; payload: unknown; summary: string; rows: Row[] }
const modes: { id: Mode; label: string; permission: string }[] = [
  { id: 'mail', label: '指定多人邮件', permission: 'players.mail' },
  { id: 'items/grant', label: '批量物品及装备', permission: 'players.items' },
  { id: 'currency-adjust', label: '批量增加货币', permission: 'players.currency' },
]
const storageKey = 'mhq-gm-batch-v1'
function restore(owner: string): Plan | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) || 'null') as Plan | null
    return value?.owner === owner && Array.isArray(value.rows) && value.rows.length <= 20 ? value : null
  } catch { return null }
}
const statusLabels: Record<string, string> = { ready: '待发送', completed: '已完成', rejected: '已拒绝', pending: '等待确认', accepted: '等待确认', error: '请求失败，可重试' }

export function Batch() {
  const session = useAuth()
  const allowed = modes.filter(mode => can(session, mode.permission))
  const [mode, setMode] = useState<Mode>(allowed[0]?.id || 'mail')
  const [targets, setTargets] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [currency, setCurrency] = useState('coin')
  const [amount, setAmount] = useState('')
  const [items, setItems] = useState<SelectedItem[]>([])
  const [plan, setPlan] = useState<Plan | null>(() => restore(session?.adminId || ''))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = (value: Plan | null) => {
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value)); else sessionStorage.removeItem(storageKey)
    setPlan(value)
  }
  const prepare = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || plan) return
    setError('')
    const ids = [...new Set(targets.trim().split(/[\s,，;；]+/))]
    if (!ids.length || ids.length > 20 || ids.some(id => !/^[1-9]\d{0,18}$/.test(id) || BigInt(id) > 9223372036854775807n)) { setError('请填写 1 至 20 个有效角色 ID，以空格或逗号分隔'); return }
    const itemError = itemSelectionError(items, mode === 'items/grant')
    if (mode !== 'currency-adjust' && itemError) { setError(itemError); return }
    if (mode === 'mail' && (!title.trim() || !content.trim() || new TextEncoder().encode(title).length > 191 || new TextEncoder().encode(content).length > 4000)) { setError('邮件须有标题和正文，分别不超过 191 和 4000 字节'); return }
    if (mode === 'currency-adjust' && (!/^\d+(\.\d{1,4})?$/.test(amount) || Number(amount) <= 0 || Number(amount) > 1_000_000_000 || (currency !== 'coin' && !/^\d+$/.test(amount)))) { setError('数量须大于 0 且不超过十亿；仅金币允许最多四位小数'); return }
    setBusy(true)
    try {
      // Resolve every ID before the first write. The server still rechecks
      // permission, visibility, inventory capacity and business constraints.
      const players = await Promise.all(ids.map(id => api.player(id)))
      const batchKey = newIdempotencyKey()
      const payload = mode === 'mail' ? { title: title.trim(), content, items: itemSelectionPayload(items) }
        : mode === 'items/grant' ? { items: itemSelectionPayload(items) } : { currency, delta: amount }
      const attachmentSummary = items.map(value => `${value.item.name}（${value.item.id}）× ${value.count}`).join('、') || '无附件'
      const currencyNames: Record<string, string> = { coin: '金币', yuanBao: '元宝', voucher: '代金券', starCoin: '星币', honor: '荣誉', pvpCurrency: '竞技币' }
      const summary = mode === 'mail' ? `标题：${title.trim()}\n正文：${content}\n附件：${attachmentSummary}`
        : mode === 'items/grant' ? `每人发放：${attachmentSummary}` : `每人增加：${amount} ${currencyNames[currency]}`
      save({ owner: session!.adminId, mode, payload, summary, rows: players.map(player => ({ id: player.id, name: player.name, key: `${batchKey}-${player.id}`, status: 'ready', message: '' })) })
    } catch (err) { setError(`尚未发送：${err instanceof Error ? err.message : '角色核对失败'}`) }
    finally { setBusy(false) }
  }
  const execute = async () => {
    if (!plan || busy) return
    setBusy(true); setError('')
    const current = structuredClone(plan)
    try {
      for (const row of current.rows) {
        if (row.status === 'completed' || row.status === 'rejected') continue
        try {
          // Retrying uses the same command key, including after a page reload.
          const result = await api.playerCommand(row.id, current.mode, current.payload, row.key)
          row.status = String(result.status || 'pending')
          row.message = String(result.message || '')
        } catch (err) {
          const failure = err as Error & { status?: number; data?: { status?: string } }
          row.status = failure.data?.status === 'rejected' || [400, 401, 403, 404, 409, 422].includes(failure.status || 0) ? 'rejected' : 'error'
          row.message = failure.message || '请求失败'
        }
        save(structuredClone(current))
      }
    } finally { setBusy(false) }
  }
  const refresh = async () => {
    if (!plan || busy) return
    setBusy(true)
    const current = structuredClone(plan)
    try {
      for (const row of current.rows.filter(row => row.status === 'pending' || row.status === 'accepted' || row.status === 'error')) {
        try { const result = await api.command(row.key); row.status = result.status; row.message = result.errorCode || '' }
        catch (err) { row.message = err instanceof Error ? err.message : '状态查询失败' }
      }
      save(current)
    } finally { setBusy(false) }
  }
  if (!allowed.length) return <Card className="card-pad">当前管理员没有指定玩家发放权限。</Card>
  return <><PageHeader title="指定玩家批量操作" description="先核对所有角色，再逐人调用游戏业务；每人独立记录结果，部分失败不会伪报整批成功" />
    {error ? <div className="notice danger" role="alert">{error}</div> : null}
    {!plan ? <Card className="card-pad"><form onSubmit={prepare}>
      <Field label="操作类型"><select className="select" value={mode} disabled={busy} onChange={e => setMode(e.target.value as Mode)}>{allowed.map(value => <option key={value.id} value={value.id}>{value.label}</option>)}</select></Field>
      <Field label="角色 ID" hint="最多 20 个，以空格、逗号或换行分隔；重复 ID 仅处理一次"><textarea className="textarea" value={targets} disabled={busy} onChange={e => setTargets(e.target.value)} required /></Field>
      {mode === 'mail' ? <><Field label="邮件标题"><input className="input" value={title} disabled={busy} onChange={e => setTitle(e.target.value)} required /></Field><Field label="邮件正文"><textarea className="textarea" value={content} disabled={busy} onChange={e => setContent(e.target.value)} required /></Field></> : null}
      {mode !== 'currency-adjust' ? <ItemPicker items={items} onChange={setItems} disabled={busy} optional={mode === 'mail'} /> : <div className="field-row"><Field label="货币"><select className="select" value={currency} onChange={e => setCurrency(e.target.value)} disabled={busy}><option value="coin">金币（1 金 = 10000 铜）</option><option value="yuanBao">元宝</option><option value="voucher">代金券</option><option value="starCoin">星币</option><option value="honor">荣誉</option><option value="pvpCurrency">竞技币</option></select></Field><Field label="每人增加数量"><input className="input" value={amount} disabled={busy} onChange={e => setAmount(e.target.value)} required /></Field></div>}
      <Button type="submit" loading={busy}>核对收件角色</Button>
    </form></Card> : <Card className="card-pad">
      <h2>{modes.find(value => value.id === plan.mode)?.label} · {plan.rows.length} 人</h2>
      <div className="notice" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{plan.summary}</div>
      <div className="notice">请核对角色与内容。确认后逐人执行；邮件附件须由玩家领取。重试沿用原命令，已完成的角色不会再次发放。本页会在当前浏览器标签页保存未完成批次。</div>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>角色</th><th>状态</th><th>说明</th><th>命令编号</th></tr></thead><tbody>{plan.rows.map(row => <tr key={row.id}><td><Link to={`/players/${row.id}`}>{row.name} #{row.id}</Link></td><td><StatusPill status={row.status}>{statusLabels[row.status] || row.status}</StatusPill></td><td>{row.message || '—'}</td><td className="mono">{row.key}</td></tr>)}</tbody></table></div>
      <div className="modal-actions"><Button disabled={busy || plan.rows.every(row => ['completed', 'rejected'].includes(row.status))} loading={busy} onClick={() => void execute()}>确认执行 / 重试未完成项</Button><Button variant="secondary" disabled={busy} onClick={() => void refresh()}>查询执行结果</Button><Button variant="ghost" disabled={busy || plan.rows.some(row => ['pending', 'accepted', 'error'].includes(row.status))} onClick={() => save(null)}>结束本批次</Button></div>
    </Card>}
  </>
}
