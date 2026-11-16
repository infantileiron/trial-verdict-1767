import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {table} from '../components/common/table.js';import {field,select} from '../components/common/fields.js';import {badge} from '../components/common/status.js';import {time} from '../utils/format.js';import {ALIAS_JOB_STATES,ALIAS_ITEM_STATES} from '../constants/enums.js';
function metric(label,value,sub='',cls=''){return `<div class="metric ${cls}"><span>${esc(label)}</span><strong>${esc(String(value))}</strong>${sub?`<small>${esc(sub)}</small>`:''}</div>`}
export function render(){
 const exp=state.experiments.find(e=>String(e.id)===String(state.lookupExp||state.experiments[0]?.id));
 const rep=exp?.identity;
 const polluted=rep?.polluted||[];
 return `<div class="split"><section>
 <h2>身份归并与去重口径</h2>
 <form id="identity-exp" class="inline">${select('选择实验查看口径','experiment_id',state.experiments.map(e=>[e.id,e.code+' · '+e.name]))}</form>
 <p class="notice">访客登录前后标识不同会被重复计数。导入别名关联后按 canonical 身份归并；原始事件与关联依据全程保留。同一身份落入 A、B 两组将单列为污染并阻断发布，不任选一组、不悄悄剔除。</p>
 ${exp?`<div class="eyebrow">${esc(exp.code)} · 身份关系版本 v${esc(String(rep.identity_version))}</div>
 <div class="metrics">
 ${metric('原始曝光（标识数）',rep.raw_exposed_total,`A ${rep.raw_exposed_a} / B ${rep.raw_exposed_b}`)}
 ${metric('去重曝光（人数）',rep.dedup_exposed_total,`A ${rep.n_a} / B ${rep.n_b}`)}
 ${metric('去重激活（人数）',rep.activated_a+rep.activated_b,`A ${rep.activated_a} / B ${rep.activated_b}`)}
 ${metric('污染身份',rep.polluted_count,'跨 A/B 同一人',rep.polluted_count?'danger':'good')}
 </div>
 <h3>污染身份明细（阻断发布依据）</h3>
 ${polluted.length?table(['canonical 身份','落入组别','原始标识'],polluted.map(p=>[p.identity,p.groups.join('、'),p.user_keys.join('、')])):'<p class="muted">当前实验无跨组污染身份。</p>'}`:'<p class="notice">请先建立实验并采集事件。</p>'}
 <h3>归并链追查</h3>
 <form id="lookup" class="inline">${field('输入要追查的标识 user_key','user_key','text','required')}<button class="primary">追查归并链</button></form>
 <div id="lookup-result">${renderLookup(state.lookup)}</div>
 <h3>关联任务（待处理 / 完成 / 失败，可恢复重试）</h3>
 <div class="records">${state.aliasJobs.map(j=>`<article class="experiment"><div class="eyebrow">任务 #${j.id} ${badge(ALIAS_JOB_STATES[j.state]||j.state)}</div><p class="meta">${esc(j.note||j.source)} · ${time(j.created)}<br>处理 ${j.processed_items} 条 · 失败 ${j.failed_items} 条 · 归并 ${j.applied_merges} 次 · 版本 v${j.identity_version_before}→v${j.identity_version_after}${j.error?`<br><span class="error">${esc(j.error)}</span>`:''}</p><div class="scroll"><table><thead><tr><th>关联 A</th><th>关联 B</th><th>状态</th><th>说明 / 依据</th></tr></thead><tbody>${(j.items||[]).map(it=>`<tr><td>${esc(it.a_key)}</td><td>${esc(it.b_key)}</td><td>${esc(ALIAS_ITEM_STATES[it.state]||it.state)}</td><td>${esc(it.message||'')}</td></tr>`).join('')}</tbody></table></div>${j.state==='failed'&&state.user.role!=='viewer'?`<button data-retry="${j.id}">恢复 / 重试该任务</button>`:''}</article>`).join('')||'<p class="muted">暂无关联任务。</p>'}</div>
 </section>
 <aside>
 <h2>导入别名关联</h2>
 <form id="aliasjob">
 ${select('适用实验（用于口径预览）','experiment_id',state.experiments.map(e=>[e.id,e.name]))}
 <label>来源说明<input name="note" type="text" maxlength="300" placeholder="如 登录账号映射批次 1116"></label>
 <label>关联对（每行一对，用空格、逗号或制表符分隔两个标识）<textarea name="pairs" rows="9" required placeholder="LJ-U0001,LJ-G0001&#10;LJ-U0002 LJ-G0002"></textarea></label>
 <p class="muted">每行一对，最多 1000 对。重复或已同身份的关联幂等跳过，重试不重复改变人数。</p>
 <button class="primary">提交关联处理</button>
 </form>
 </aside></div>`}
export function renderLookup(l){
 if(!l)return '<p class="muted">输入标识后展示其 canonical 身份、全部别名、归并历史与原始关联依据。</p>';
 if(!l.identity)return `<p class="notice">${esc(l.query)}：${esc(l.note)}</p>`;
 return `<article class="experiment"><div class="eyebrow">${esc(l.query)} → canonical ${esc(l.identity)} · 版本 v${esc(String(l.identity_version))}</div>
 <p class="meta">全部别名：${l.aliases.map(esc).join('、')}</p>
 <h4>归并历史</h4>${l.merges.length?table(['左身份','右身份','归并后','版本','依据任务','时间'],l.merges.map(m=>[m.left_id,m.right_id,m.merged_id,'v'+m.identity_version,'#'+m.alias_job_id,time(m.created)])):'<p class="muted">该身份由新关联直接建立，无身份间归并。</p>'}
 <h4>原始关联依据（留痕）</h4>${table(['标识 A','标识 B','状态','任务','时间'],l.links.map(x=>[x.a_key,x.b_key,x.state,'#'+x.alias_job_id,time(x.created)]))}</article>`}
