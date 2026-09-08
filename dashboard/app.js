const state={run:null,agents:[],skills:[],tools:[],providers:[],workProfiles:[],orchestration:null};
const $=id=>document.getElementById(id);
const api=async(path,options)=>{const r=await fetch(path,options);if(!r.ok){const e=await r.json();throw new Error(e.detail||r.statusText)}return r.json()};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metric=(label,value)=>`<div class="metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
const rows=(items,empty='No data')=>items.length?items.join(''):`<div class="empty">${esc(empty)}</div>`;
const tags=items=>(items||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join('');
const fmt=x=>x==null?'Unavailable':Number(x).toLocaleString();
const pct=x=>x==null?'Unavailable':Math.round(x*100)+'%';
const row=(label,value)=>`<div class="row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;

async function shell(){const [orchestration,health,bootstrap]=await Promise.all([api('/api/orchestration'),api('/api/health'),api('/api/bootstrap-status')]);state.orchestration=orchestration;$('version').textContent='v'+health.version;$('ownerBadge').textContent=`Owner: ${orchestration.owner==='universal-agent-platform'?'Platform':orchestration.owner}`;$('bootstrapHealth').innerHTML=metric('Platform installation',bootstrap.platform_installation.toUpperCase())+metric('Project initialization',bootstrap.project_initialization.toUpperCase())+metric('Ready providers',bootstrap.provider_availability)+metric('Active profiles',bootstrap.profiles_active)+metric('Consumption',bootstrap.consumption.mode.toUpperCase())+metric('Health',bootstrap.health.toUpperCase())}

// -- Overview ----------------------------------------------------------------

async function loadRuns(){const runs=await api('/api/runs');$('runSelect').innerHTML=runs.map(r=>`<option value="${esc(r.id)}">${esc(r.id)} — ${esc(r.goal)}</option>`).join('');if(runs.length){state.run=state.run||runs[0].id;$('runSelect').value=state.run;await loadRun()}else{$('liveTeam').innerHTML='<div class="empty">No runs yet</div>';$('whyTeam').innerHTML='<div class="empty">Run a goal to see how the team was chosen</div>'}}
async function loadRun(){state.run=$('runSelect').value;const id=encodeURIComponent(state.run);const [run,tokens,caps,routing,performance,efficiency,composition]=await Promise.all([api(`/api/runs/${id}`),api(`/api/token-usage?run_id=${id}`),api('/api/capabilities'),api(`/api/routing?run_id=${id}`),api('/api/performance'),api(`/api/efficiency?run_id=${id}`),api(`/api/runs/${id}/composition`)]);renderRun(run,tokens,caps,routing,performance,efficiency,composition)}

function renderRun(run,tokens,caps,routing,performance,efficiency,composition){
  const tasks=run.tasks||[],total=tokens.reduce((n,t)=>n+t.total_tokens,0);
  const invocations=tokens.reduce((n,t)=>n+(t.invocations||0),0);
  const deterministic=tasks.filter(t=>t.kind&&t.kind!=='agent').length;
  const profiles=(composition.work_profiles||[]).join(', ')||'inferred';
  const consumption=composition.consumption||{},limits=consumption.limits||consumption;
  $('metrics').innerHTML=metric('Run status',run.status)+metric('Work profiles',profiles)+metric('Consumption',consumption.mode||'balanced')+metric('Team limit',limits.max_team_members==null?'profile default':limits.max_team_members)+metric('Tasks',tasks.length)+metric('AI invocations',invocations||tasks.filter(t=>!t.kind||t.kind==='agent').length)+metric('Deterministic steps',deterministic)+metric('Tokens',total.toLocaleString());
  renderTeam(composition);
  $('dag').innerHTML=rows(tasks.map(t=>{const kind=t.kind||'agent',routed=t.data.metadata?.model||(kind==='agent'?'unrouted':'no AI');return `<div class="node ${esc(t.status)} kind-${esc(kind)}" data-task="${esc(t.id)}"><div class="owner">${esc(t.owner)} · ${esc(routed)}</div><div>${esc(t.title)}</div><span class="pill">${esc(t.status)}</span><span class="pill kind">${esc(kind)}</span><small>${esc(t.id)} · dependencies: ${esc((t.data.dependencies||[]).join(', ')||'none')}</small></div>`}),'No tasks');
  document.querySelectorAll('.node').forEach(n=>n.onclick=()=>showTask(tasks.find(t=>t.id===n.dataset.task),tokens));
  $('tokens').innerHTML=rows(tokens.map(t=>`<div class="row"><span>${esc(t.agent)}<br><small>${esc(t.provider||'unattributed')}</small></span><strong>${t.token_source==='estimated'?'~':''}${fmt(t.total_tokens)}<br><small>${esc(t.token_source)}</small></strong></div>`),'No usage yet');
  $('capabilities').innerHTML=row('Missing',caps.missing.length)+row('Temporary specialists',caps.temporary_specialists.length)+row('Promotion candidates',caps.promotion_candidates.length);
  renderRouting(composition,routing);
  $('performance').innerHTML=rows(performance.map(x=>`<div class="row"><span>${esc(x.agent_role)} / ${esc(x.model)}</span><strong>${x.task_count} tasks · ${pct(x.success_rate)}</strong></div>`),'Not enough history');
  $('efficiency').innerHTML=rows(efficiency.map(x=>`<div class="row"><span>${esc(x.message)}</span><strong>${esc(x.recommendation)}</strong></div>`),'No efficiency warnings');
  $('timeline').innerHTML=rows((run.events||[]).map(e=>`<div class="event"><span>${new Date(e.timestamp).toLocaleTimeString()}</span><strong>${esc(e.event)}</strong><span>${esc(e.agent||'system')} ${esc(e.task_id||'')}</span></div>`),'No events');
}

function renderTeam(composition){
  const team=composition.team||{},members=team.members||[];
  const routed={};(composition.routing||[]).forEach(t=>{if(t.provider)routed[t.owner]={provider:t.provider,model:t.model,status:t.status}});
  $('liveTeam').innerHTML=rows(members.map(m=>{const r=routed[m.role_id]||{};return `<div class="team-member"><div class="card-title"><strong>${esc(m.name)}</strong><span class="badge ${esc(m.origin)}">${esc(m.origin==='temporary_specialist'?'temporary':m.evaluative?'evaluation':m.profile||'role')}</span></div><small>${esc(m.responsibility)}</small><div class="meta">${esc(r.provider||'unrouted')} · ${esc(r.model||'no model')}</div><div>${tags(m.skills)}</div></div>`}),'No team composed');
  const why=[];
  (team.rationale||[]).forEach(line=>why.push(`<li>${esc(line)}</li>`));
  const omitted=(team.omitted||[]).slice(0,6).map(o=>`<div class="row"><span>${esc(o.role)}</span><strong class="muted">${esc(o.reason)}</strong></div>`);
  $('whyTeam').innerHTML=(why.length?`<ul class="rationale">${why.join('')}</ul>`:'<div class="empty">No rationale recorded</div>')
    +(omitted.length?`<h3>Deliberately omitted</h3>${omitted.join('')}`:'')
    +(team.capability_signature?`<div class="row"><span>Capability signature</span><strong class="path">${esc(team.capability_signature)}</strong></div>`:'');
}

function renderRouting(composition,routing){
  const decisions=(composition.routing||[]).filter(t=>t.routing&&t.routing.provider);
  const source=decisions.length?decisions:routing.map(x=>({id:x.id,owner:x.routing.agent,routing:x.routing,provider:x.routing.provider,model:x.routing.model}));
  $('routing').innerHTML=rows(source.map(t=>{const d=t.routing||{},reasons=(d.reasons||[d.reason]).filter(Boolean);
    return `<div class="decision"><div class="card-title"><strong>${esc(t.owner||d.agent)}</strong><span class="pill">${esc(d.provider)} / ${esc(d.model||'none')}</span></div>`
      +(d.required_capabilities&&d.required_capabilities.length?`<div>Required: ${tags(d.required_capabilities)}</div>`:'')
      +`<ul class="rationale">${reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`
      +((d.candidates||[]).some(c=>c.disqualified)?`<h3>Rejected providers</h3>${(d.candidates||[]).filter(c=>c.disqualified).map(c=>row(c.provider,c.disqualified)).join('')}`:'')
      +`</div>`}),'No routing decisions');
}

function showTask(task,tokens){const usage=tokens.filter(t=>t.task_id===task.id).reduce((n,t)=>n+t.total_tokens,0);const m=task.data.metadata||{};
  $('detail').innerHTML=row('Owner',task.owner)+row('Kind',task.kind||'agent')+row('Status',task.status)+row('Task',task.id)+row('Provider',m.provider||'none')+row('Model',m.model||'no AI invocation')+row('Reasoning',task.data.reasoning)+row('Artifact',task.data.artifact_type||'unknown')+row('Tokens',usage.toLocaleString())+(m.routing_reason?`<p class="hint">${esc(m.routing_reason)}</p>`:'')}

// -- Agents ------------------------------------------------------------------

async function loadAgents(){const [agents,profiles]=await Promise.all([api('/api/agents'),api('/api/providers/codex/profiles')]);state.agents=agents;$('agentOwner').innerHTML='<span class="pill">Agent ≠ Model</span> <span class="pill">Agent ≠ Skill</span>';$('agentMetrics').innerHTML=metric('Total Agents',agents.length)+metric('Active',agents.filter(a=>a.enabled).length)+metric('Idle',agents.filter(a=>a.status==='idle').length)+metric('Temporary',agents.filter(a=>a.type==='temporary').length)+metric('Promotion Candidates',agents.filter(a=>a.promotion_candidate).length)+metric('Disabled',agents.filter(a=>!a.enabled).length);renderAgents();$('profileCards').innerHTML=rows(profiles.map(p=>`<div class="row profile-row"><span><strong>${esc(p.name)}</strong><br><small>${esc(p.source)}</small></span><span>${esc(p.model||'inherited')} / ${esc(p.reasoning||'inherited')}<br>Advisory binding: ${esc(p.bound_to.join(', ')||'none')}</span></div>`),'No provider-native profiles detected')}
function renderAgents(){const q=$('agentSearch').value.toLowerCase(),status=$('agentStatus').value;const items=state.agents.filter(a=>(!status||a.status===status)&&JSON.stringify([a.name,a.capabilities,a.work_profile]).toLowerCase().includes(q));$('agentCards').innerHTML=rows(items.map(a=>`<article class="card registry-card" data-agent="${esc(a.id)}"><div class="card-title"><h2>${esc(a.name)}</h2><span class="badge ${esc(a.type)}">${esc(a.promotion_candidate?'promotion candidate':a.type)}</span></div><div class="status ${esc(a.status)}">● ${esc(a.status)}</div><p>${esc(a.work_profile||'unassigned profile')} · provider ${esc(a.provider)} · model ${esc(a.model)}</p><div>${tags(a.capabilities)}</div><small>Skills: ${esc(a.skills.join(', ')||'none')}</small><div class="row"><span>Success</span><strong>${pct(a.success_rate)}</strong></div><div class="row"><span>Tokens</span><strong>${a.token_estimated?'~':''}${fmt(a.token_usage)}</strong></div></article>`),'No matching agents');document.querySelectorAll('[data-agent]').forEach(n=>n.onclick=()=>showAgent(n.dataset.agent))}
async function showAgent(id){const a=await api(`/api/agents/${encodeURIComponent(id)}`);$('agentDetail').innerHTML=`<div class="card-title"><h2>${esc(a.name)}</h2><span class="badge ${esc(a.type)}">${esc(a.type)}</span></div><h3>Agent → Work Profile → Provider → Model</h3><div class="relationship">${esc(a.role)}<b>↓</b>${esc(a.work_profile||'none')}<b>↓</b>${esc(a.provider)}<b>↓</b>${esc(a.model)}</div><p class="hint">"auto" means routing decides per task from required capabilities.</p><h3>Capabilities</h3><div>${tags(a.capabilities)}</div><h3>Skills</h3><div>${a.skills.map(s=>`<a class="tag" href="/skills#${esc(s)}">${esc(s)}</a>`).join('')||'None'}</div>${row('Context',a.context_health)}${row('Current task',a.current_task?.id||'Idle')}${row('Source',a.source)}<button data-toggle-agent>${a.enabled?'Disable':'Enable'} Agent</button>`;document.querySelector('[data-toggle-agent]').onclick=async()=>{try{await api(`/api/agents/${encodeURIComponent(id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!a.enabled})});await loadAgents();await showAgent(id)}catch(e){alert(e.message)}}}

// -- Skills ------------------------------------------------------------------

async function loadSkills(){state.skills=await api('/api/skills');$('skillOwner').innerHTML='<span class="pill">Scope: Global + Current Project</span>';const s=state.skills;$('skillMetrics').innerHTML=metric('Total Skills',s.length)+metric('Global',s.filter(x=>x.scope==='global').length)+metric('Project-local',s.filter(x=>x.scope==='project').length)+metric('Currently loaded',s.filter(x=>x.loaded).length)+metric('Unused',s.filter(x=>x.load_count===0).length)+metric('Disabled',s.filter(x=>!x.enabled).length);renderSkills();if(location.hash)showSkill(location.hash.slice(1))}
function renderSkills(){const q=$('skillSearch').value.toLowerCase(),scope=$('skillScope').value;const items=state.skills.filter(s=>(!scope||s.scope===scope)&&JSON.stringify([s.name,s.capabilities]).toLowerCase().includes(q));$('skillCards').innerHTML=rows(items.map(s=>`<article class="card registry-card" data-skill="${esc(s.id)}"><div class="card-title"><h2>${esc(s.name)}</h2><span class="badge">${esc(s.scope)}</span></div><div class="status ${s.loaded?'working':'idle'}">● ${s.loaded?'currently loaded':'not loaded'}</div><p>${esc(s.description)}</p><div>${tags(s.capabilities)}</div><div class="row"><span>Used by</span><strong>${esc(s.used_by_agents.join(', ')||'none')}</strong></div><div class="row"><span>Historical loads</span><strong>${s.load_count}</strong></div></article>`),'No matching skills');document.querySelectorAll('[data-skill]').forEach(n=>n.onclick=()=>showSkill(n.dataset.skill))}
async function showSkill(id){const s=await api(`/api/skills/${encodeURIComponent(id)}`);$('skillDetail').innerHTML=`<div class="card-title"><h2>${esc(s.name)}</h2><span class="badge">${esc(s.scope)}</span></div><p>${esc(s.description)}</p><h3>Capabilities</h3><div>${tags(s.capabilities)}</div>${row('Lazy-loaded',s.lazy_load?'YES':'NO')}${row('Currently loaded by',s.loaded_by.join(', ')||'none')}${row('Agents using it',s.used_by_agents.join(', ')||'none')}${row('Token attribution',s.token_attribution)}${row('Source',s.source)}<button data-toggle-skill>${s.enabled?'Disable':'Enable'} Skill</button>`;document.querySelector('[data-toggle-skill]').onclick=async()=>{try{await api(`/api/skills/${encodeURIComponent(id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!s.enabled})});await loadSkills();await showSkill(id)}catch(e){alert(e.message)}}}

// -- Tools -------------------------------------------------------------------

async function loadTools(){state.tools=await api('/api/tools');const t=state.tools;$('toolOwner').innerHTML='<span class="pill">Allowlist enforced</span>';$('toolMetrics').innerHTML=metric('Total Tools',t.length)+metric('Project commands',t.filter(x=>x.execution==='project_command').length)+metric('Built-in',t.filter(x=>x.execution==='builtin_command').length)+metric('Needs approval',t.filter(x=>['high','destructive'].includes(x.risk)).length);renderTools()}
function renderTools(){const q=$('toolSearch').value.toLowerCase(),risk=$('toolRisk').value;const items=state.tools.filter(t=>(!risk||t.risk===risk)&&JSON.stringify([t.name,t.capabilities,t.command]).toLowerCase().includes(q));$('toolCards').innerHTML=rows(items.map(t=>`<article class="card registry-card"><div class="card-title"><h2>${esc(t.name)}</h2><span class="badge risk-${esc(t.risk)}">${esc(t.risk)}</span></div><p>${esc(t.description)}</p><div>${tags(t.capabilities)}</div>${row('Execution',t.execution)}${row('Command',t.command||'internal')}${row('Needs repository',t.requires_repository?'yes':'no')}${row('Trust',t.trust)}</article>`),'No matching tools')}

// -- Providers ---------------------------------------------------------------

async function loadProviders(){state.providers=await api('/api/providers');const p=state.providers;$('providerOwner').innerHTML='<span class="pill">Selection: auto</span> <span class="pill">Credentials never shown</span>';$('providerMetrics').innerHTML=metric('Registered',p.length)+metric('Ready',p.filter(x=>x.ready).length)+metric('Implemented',p.filter(x=>x.implemented).length)+metric('Plugin-ready',p.filter(x=>!x.implemented).length)+metric('Models',p.reduce((n,x)=>n+x.models.length,0));
  $('providerCards').innerHTML=rows(p.map(x=>`<article class="card registry-card" data-provider="${esc(x.id)}"><div class="card-title"><h2>${esc(x.name)}</h2><span class="badge status-${esc(x.status)}">${esc(x.status)}</span></div><div class="status ${x.ready?'working':'idle'}">● ${x.ready?'ready':x.implemented?'not usable now':'no adapter in this build'}</div><p>${esc(x.detail)}</p>${row('Type',x.type)}${row('Execution',x.execution_mode)}${row('Models',x.models.length)}${row('Invocations',fmt(x.usage.invocations))}${row('Recent success',pct(x.recent_success))}</article>`),'No providers registered');
  document.querySelectorAll('[data-provider]').forEach(n=>n.onclick=()=>showProvider(n.dataset.provider))}
async function showProvider(id){const p=await api(`/api/providers/${encodeURIComponent(id)}`);
  const caps=Object.entries(p.capabilities||{}).map(([k,v])=>`<div class="row"><span>${esc(k)}</span><strong class="support-${esc(v)}">${esc(v)}</strong></div>`).join('');
  $('providerDetail').innerHTML=`<div class="card-title"><h2>${esc(p.name)}</h2><span class="badge status-${esc(p.status)}">${esc(p.status)}</span></div><p>${esc(p.detail)}</p>${p.notes?`<p class="hint">${esc(p.notes)}</p>`:''}${row('Type',p.type)}${row('Execution',p.execution_mode)}${row('Implemented',p.implemented?'yes':'no adapter in this build')}${row('Trust',p.trust)}${row('Tokens',fmt(p.usage.tokens))}${row('Invocations',fmt(p.usage.invocations))}${row('Recent success',pct(p.recent_success))}${row('Recent tasks',(p.recent_tasks||[]).join(', ')||'none')}<h3>Capabilities</h3>${caps||'<div class="empty">Not reported</div>'}<h3>Models</h3>${rows(p.models.map(m=>`<div class="row"><span>${esc(m.display_name||m.model_id)}<br><small>${esc(m.tier)} · ${esc(m.cost)} cost · ${esc(m.latency)}</small></span><strong>${esc(m.enabled?'enabled':'disabled')}</strong></div>`),'No models catalogued')}`}

// -- Work Profiles -----------------------------------------------------------

async function loadWorkProfiles(){state.workProfiles=await api('/api/profiles');const p=state.workProfiles;$('profileOwner').innerHTML='<span class="pill">Starter packs, not a closed taxonomy</span>';$('profileMetrics').innerHTML=metric('Installed',p.length)+metric('Active here',p.filter(x=>x.active).length)+metric('Built-in',p.filter(x=>x.trust==='built_in').length)+metric('Suggested roles',p.reduce((n,x)=>n+x.roles.length,0));
  $('workProfileCards').innerHTML=rows(p.map(x=>`<article class="card registry-card${x.active?' active':''}" data-workprofile="${esc(x.id)}"><div class="card-title"><h2>${esc(x.name||x.id)}</h2><span class="badge">${esc(x.active?'active':x.trust)}</span></div><p>${esc(x.description)}</p><div>${tags(x.capabilities.slice(0,8))}</div>${row('Suggested roles',x.roles.map(r=>r.name).join(', ')||'none')}${row('Installed skills',x.installed_skills.join(', ')||'none')}</article>`),'No profiles installed');
  document.querySelectorAll('[data-workprofile]').forEach(n=>n.onclick=()=>showWorkProfile(n.dataset.workprofile))}
async function showWorkProfile(id){const p=await api(`/api/profiles/${encodeURIComponent(id)}`);
  $('workProfileDetail').innerHTML=`<div class="card-title"><h2>${esc(p.name||p.id)}</h2><span class="badge">${esc(p.active?'active':p.trust)}</span></div><p>${esc(p.description)}</p><h3>Capabilities</h3><div>${tags(p.capabilities)}</div><h3>Suggested roles</h3>${rows(p.roles.map(r=>`<div class="row"><span>${esc(r.name)}<br><small>${esc(r.responsibility)}</small></span><strong>${esc(r.evaluative?'evaluation':r.optional?'optional':'core')}</strong></div>`),'None')}<h3>Skills</h3><div>${tags(p.installed_skills)}</div>${p.missing_skills.length?`<p class="hint">Not installed: ${esc(p.missing_skills.join(', '))}</p>`:''}<h3>Tools</h3><div>${tags(p.available_tools)}</div><h3>Evaluation</h3>${rows(p.evaluation_strategies.map(e=>`<div class="row"><span>${esc(e.name)}</span><strong>${esc(e.kind)}</strong></div>`),'None declared')}<h3>Artifacts</h3><div>${tags(p.artifact_types)}</div>${p.approval_gates.length?`<h3>Approval gates</h3><div>${tags(p.approval_gates)}</div>`:''}${row('Source',p.source)}<p class="hint">Editable without changing core: drop a YAML file into the platform profiles directory.</p>`}

// -- Wiring ------------------------------------------------------------------

$('theme').onclick=()=>document.documentElement.classList.toggle('dark');
$('runSelect').addEventListener('change',loadRun);
$('agentSearch').oninput=renderAgents;$('agentStatus').onchange=renderAgents;
$('skillSearch').oninput=renderSkills;$('skillScope').onchange=renderSkills;
$('toolSearch').oninput=renderTools;$('toolRisk').onchange=renderTools;

const PAGES={'/':['overviewPage',loadRuns],'/agents':['agentsPage',loadAgents],'/skills':['skillsPage',loadSkills],'/tools':['toolsPage',loadTools],'/providers':['providersPage',loadProviders],'/profiles':['profilesPage',loadWorkProfiles]};
const page=PAGES[location.pathname]?location.pathname:'/';
Object.entries(PAGES).forEach(([path,[element]])=>$(element).classList.toggle('hidden',path!==page));
document.querySelectorAll('.topnav a').forEach(a=>{if(a.getAttribute('href')===page)a.classList.add('current')});
const load=PAGES[page][1];
shell().then(load).catch(e=>{const main=document.querySelector('main:not(.hidden)');if(main)main.innerHTML=`<div class="card empty">${esc(e.message)}</div>`});
// Providers, profiles and tools are static registries; only live pages re-fetch.
const stream=new EventSource('/api/events/live');
stream.onmessage=()=>{if(page==='/agents')loadAgents();else if(page==='/skills')loadSkills();else if(page==='/'&&state.run)loadRun()};
stream.onerror=()=>{const c=$('connection');if(c){c.textContent='● offline';c.classList.add('offline')}};
