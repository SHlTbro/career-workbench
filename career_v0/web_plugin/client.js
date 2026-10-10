window.__ModuleLoader__.load({
  id: 'career-v0-web-plugin',
  factory: (require) => {
    const React = require('react');
    const h = React.createElement;
    const API = '/api/career-v0';

    async function request(path, options = {}) {
      const response = await fetch(API + path, { cache: 'no-store', ...options });
      let body;
      try { body = await response.json(); }
      catch { throw new Error(`Host response ${response.status} is not JSON`); }
      if (!response.ok || !body.ok) throw new Error(body.error || `Host response ${response.status}`);
      return body;
    }
    const post = (path, body) => request(path, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    const query = (value) => encodeURIComponent(value);
    const split = (value) => String(value || '').split(/[,，\n]/).map((part) => part.trim()).filter(Boolean);
    const field = (label, input, help) => h('label', { className: 'career-field' },
      h('span', null, label), input, help && h('small', null, help));
    const input = (value, change, placeholder = '') => h('input', {
      value: value ?? '', placeholder, onChange: (event) => change(event.target.value),
    });
    const choice = (value, change, options) => h('select', {
      value: value ?? '', onChange: (event) => change(event.target.value),
    }, h('option', { value: '' }, '请选择'), ...options.map(([key, label]) => h('option', { key, value: key }, label)));
    const yesNo = [['true', '包含 / 允许'], ['false', '不包含 / 不允许']];
    const boolText = (value) => value === true ? 'true' : value === false ? 'false' : '';
    const parseBool = (value) => value === '' ? null : value === 'true';
    const btn = (label, onClick, disabled = false, extra = {}) => h('button', {
      type: 'button', onClick, disabled, ...extra,
    }, label);
    const panel = (title, ...children) => h('section', { className: 'career-panel' }, h('h2', null, title), ...children);
    const clone = (value) => JSON.parse(JSON.stringify(value));
    const stableStringify = (value) => JSON.stringify((function canonical(item) {
      if (Array.isArray(item)) return item.map(canonical);
      if (item && typeof item === 'object') return Object.fromEntries(
        Object.keys(item).sort().map((key) => [key, canonical(item[key])]));
      return item;
    })(value));

    function emptyForm(inventory) {
      const source = clone(inventory);
      source.projects = source.projects.map((project) => ({ ...project, _stack_text: '' }));
      return {
        recruitment_type: 'AUTUMN_CAMPUS', allow_internships: false, graduation_year: 2027,
        target_roles: [], city_scope: { mode: '', values: [] }, company_scope: '',
        company_filters: { names: [], sizes: [] },
        adjacent_role_policy: { frontend: null, algorithm: null, sales: null },
        salary: { currency: 'CNY', basis: 'PRE_TAX_BASE_MONTHLY', comparison: '',
          minimum: null, unknown_policy: '' }, batch_target_count: 50,
        project_inventory: source,
        identity_signals: Object.fromEntries(['ID-PLATFORMS', 'ID-PROJECTS', 'ID-PROVENANCE'].map((id) =>
          [id, { owner_confirmed: false, source_quote: '', approved_expression: '' }])),
        _roles_text: '', _cities_text: '', _company_names_text: '', _company_sizes_text: '',
      };
    }
    function hydrate(saved, inventory) {
      const value = { ...emptyForm(inventory), ...clone(saved) };
      value._roles_text = (value.target_roles || []).join(', ');
      value._cities_text = (value.city_scope?.values || []).join(', ');
      value._company_names_text = (value.company_filters?.names || []).join(', ');
      value._company_sizes_text = (value.company_filters?.sizes || []).join(', ');
      value.project_inventory.projects = value.project_inventory.projects.map((project) => ({
        ...project, _stack_text: (project.core_stack || []).join(', '),
      }));
      return value;
    }
    function payload(form) {
      const value = clone(form);
      value.target_roles = split(value._roles_text);
      value.city_scope.values = split(value._cities_text);
      value.company_filters.names = split(value._company_names_text);
      value.company_filters.sizes = split(value._company_sizes_text);
      value.salary.minimum = value.salary.minimum === '' || value.salary.minimum == null
        ? null : Number(value.salary.minimum);
      value.batch_target_count = Number(value.batch_target_count);
      value.project_inventory.projects = value.project_inventory.projects.map((project) => {
        project.core_stack = split(project._stack_text);
        delete project._stack_text;
        return project;
      });
      delete value._roles_text;
      delete value._cities_text;
      delete value._company_names_text;
      delete value._company_sizes_text;
      return value;
    }

    function CareerWorkbench() {
      const [state, setState] = React.useState(null);
      const [form, setForm] = React.useState(null);
      const [campaign, setCampaign] = React.useState(null);
      const [savedHash, setSavedHash] = React.useState('');
      const [tab, setTab] = React.useState('G0');
      const [busy, setBusy] = React.useState('');
      const [error, setError] = React.useState('');
      const [notice, setNotice] = React.useState('');
      const [masterText, setMasterText] = React.useState(null);
      const [batches, setBatches] = React.useState([]);
      const [batch, setBatch] = React.useState(null);
      const [exports, setExports] = React.useState([]);
      const [exportId, setExportId] = React.useState('');
      const [selection, setSelection] = React.useState(null);
      const [previews, setPreviews] = React.useState([]);
      const [preview, setPreview] = React.useState(null);
      const [acceptShortfall, setAcceptShortfall] = React.useState(false);
      const [search, setSearch] = React.useState(null);
      const [discoveries, setDiscoveries] = React.useState([]);
      const [discovery, setDiscovery] = React.useState(null);
      const [normalized, setNormalized] = React.useState([]);
      const [selectedNormalized, setSelectedNormalized] = React.useState([]);
      const [file, setFile] = React.useState(null);
      const [selectedJobs, setSelectedJobs] = React.useState([]);
      const [researchRows, setResearchRows] = React.useState([]);
      const [companySources, setCompanySources] = React.useState([]);
      const [companyDossiers, setCompanyDossiers] = React.useState([]);
      const [planRows, setPlanRows] = React.useState([]);
      const [planExports, setPlanExports] = React.useState([]);
      const [planExportId, setPlanExportId] = React.useState('');
      const [planPreviews, setPlanPreviews] = React.useState([]);
      const [planPreview, setPlanPreview] = React.useState(null);
      const [planDecisions, setPlanDecisions] = React.useState([]);
      const [planFile, setPlanFile] = React.useState(null);
      const [resumeArtifacts, setResumeArtifacts] = React.useState([]);
      const [activeArtifactId, setActiveArtifactId] = React.useState('');
      const [g3Checks, setG3Checks] = React.useState({ both_pages_readable: false,
        no_clipping_or_overlap: false, all_projects_visible: false });
      const [g3Comment, setG3Comment] = React.useState('');
      const [handoffs, setHandoffs] = React.useState([]);

      async function run(label, action) {
        setBusy(label); setError(''); setNotice('');
        try { await action(); }
        catch (cause) { setError(cause?.message || String(cause)); }
        finally { setBusy(''); }
      }
      async function reload() {
        const current = await request('/state');
        setState(current);
        if (!form) {
          const last = [...current.campaigns].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))[0];
          if (last) {
            setCampaign(last);
            setForm(hydrate(last.preferences, current.inventory));
            setSavedHash(stableStringify(last.preferences));
            if (last.status === 'PREFERENCE_CONFIRMED') {
              const batchList = await request(`/batches?campaign_id=${query(last.campaign_id)}`);
              setBatches(batchList.batches);
              const latest = batchList.batches.at(-1);
              if (latest) await chooseBatch(latest.batch_id);
            }
          } else setForm(emptyForm(current.inventory));
        }
      }
      React.useEffect(() => { run('加载工作台', reload); }, []);
      function update(mutator) { setForm((old) => { const next = clone(old); mutator(next); return next; }); }
      function chooseCampaign(id) {
        if (!id) { setCampaign(null); setForm(emptyForm(state.inventory)); setSavedHash(''); }
        else {
          const selected = state.campaigns.find((item) => item.campaign_id === id);
          setCampaign(selected); setForm(hydrate(selected.preferences, state.inventory));
          setSavedHash(stableStringify(selected.preferences));
        }
        setBatches([]); setBatch(null); setPreview(null); setPreviews([]); setSelection(null); setSearch(null); setAcceptShortfall(false);
        setDiscoveries([]); setDiscovery(null); setNormalized([]); setSelectedNormalized([]);
        setSelectedJobs([]); setResearchRows([]); setCompanySources([]); setCompanyDossiers([]); setPlanRows([]); setPlanExports([]);
        setPlanExportId(''); setPlanPreviews([]); setPlanPreview(null); setPlanDecisions([]);
        setResumeArtifacts([]); setActiveArtifactId('');
        setHandoffs([]);
      }
      const currentPayload = form ? payload(form) : null;
      const dirty = !campaign || savedHash !== stableStringify(currentPayload);
      async function saveDraft() {
        const value = payload(form);
        const result = campaign
          ? await post('/campaign/revise', { campaign_id: campaign.campaign_id, preferences: value })
          : await post('/campaign/draft', { preferences: value });
        setCampaign(result.campaign); setSavedHash(stableStringify(value));
        setState((old) => ({ ...old, campaigns: [
          ...old.campaigns.filter((item) => item.campaign_id !== result.campaign.campaign_id), result.campaign,
        ] }));
        setNotice('草稿已保存。确认 G0 需要另一次明确操作。');
      }
      async function loadMaster() {
        const response = await fetch(`${API}/master`, { cache: 'no-store' });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.error || `Master 读取失败：${response.status}`);
        }
        setMasterText(await response.text());
      }
      async function confirmG0() {
        const result = await post('/campaign/confirm', { campaign_id: campaign.campaign_id });
        setCampaign(result.campaign);
        setState((old) => ({ ...old, campaigns: old.campaigns.map((item) =>
          item.campaign_id === result.campaign.campaign_id ? result.campaign : item) }));
        setNotice(`G0 已由当前 Host 操作确认：${result.campaign.campaign_id} · r${result.campaign.revision}`);
      }
      async function loadBatches() {
        const result = await request(`/batches?campaign_id=${query(campaign.campaign_id)}`);
        setBatches(result.batches); setNotice(result.batches.length ? `找到 ${result.batches.length} 个批次。` : '目前没有可导出候选岗位的批次。');
      }
      async function chooseBatch(id) {
        if (!id) { setBatch(null); setExports([]); setExportId(''); setSelection(null); setPreview(null); setPreviews([]); setAcceptShortfall(false); setSelectedJobs([]); setResearchRows([]); setCompanySources([]); setCompanyDossiers([]); setPlanRows([]); setResumeArtifacts([]); setActiveArtifactId(''); setHandoffs([]); return; }
        const [detail, history, selectionState, previewHistory] = await Promise.all([
          request(`/batch?batch_id=${query(id)}`),
          request(`/candidate-exports?batch_id=${query(id)}`),
          request(`/selection?batch_id=${query(id)}`),
          request(`/selection-previews?batch_id=${query(id)}`),
        ]);
        setBatch(detail.batch); setExports(history.exports); setExportId(history.exports.at(-1)?.export_id || '');
        setSelection(selectionState.selection); setPreviews(previewHistory.previews); setPreview(null); setAcceptShortfall(false);
        if (selectionState.selection) await loadM2(id);
        else { setSelectedJobs([]); setResearchRows([]); setCompanySources([]); setCompanyDossiers([]); setPlanRows([]); setPlanExports([]); setPlanPreviews([]); setPlanDecisions([]); setResumeArtifacts([]); setActiveArtifactId(''); setHandoffs([]); }
      }
      async function download() {
        const response = await fetch(`${API}/candidates/workbook?batch_id=${query(batch.batch_id)}`, { cache: 'no-store' });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.error || `下载失败：${response.status}`);
        }
        const blob = await response.blob();
        const id = response.headers.get('x-career-export-id');
        if (!id) throw new Error('Host 未返回 export_id；不允许将此文件用于回读');
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url; link.download = `candidate_jobs_${batch.batch_id}_${id}.xlsx`;
        document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        setExportId(id);
        const history = await request(`/candidate-exports?batch_id=${query(batch.batch_id)}`);
        setExports(history.exports);
        setNotice(`XLSX 已导出，版本 ${id}。请离线审阅并在表中明确勾选，然后回传。`);
      }
      async function upload() {
        if (!file || !exportId) throw new Error('请先选择导出版本和 XLSX 文件');
        const result = await request(`/candidates/preview?export_id=${query(exportId)}`, {
          method: 'POST', headers: { 'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
          body: file,
        });
        setPreview(result.preview); setPreviews((old) => [...old, result.preview]); setAcceptShortfall(false);
        setNotice('已回读并生成预览。尚未确认 G1。');
      }
      async function confirmG1() {
        const result = await post('/candidates/confirm', { preview_id: preview.preview_id,
          accept_shortfall: acceptShortfall });
        setSelection(result.selection); setNotice(`G1 已确认：${result.selection.selection_id}`);
        setPreview(null);
        await loadM2(batch.batch_id);
      }
      async function loadM2(batchId) {
        const [selected, research, companySourceResult, companyDossierResult, plans, exports, previews, decisions, artifacts] = await Promise.all([
          request(`/selected-jobs?batch_id=${query(batchId)}`),
          request(`/research?batch_id=${query(batchId)}`),
          request(`/company-sources?batch_id=${query(batchId)}`),
          request(`/company-dossiers?batch_id=${query(batchId)}`),
          request(`/plans?batch_id=${query(batchId)}`),
          request(`/plan-exports?batch_id=${query(batchId)}`),
          request(`/plan-previews?batch_id=${query(batchId)}`),
          request(`/plan-decisions?batch_id=${query(batchId)}`),
          request(`/resume-artifacts?batch_id=${query(batchId)}`),
        ]);
        setSelectedJobs(selected.jobs); setResearchRows(research.research); setPlanRows(plans.plans);
        setCompanySources(companySourceResult.sources); setCompanyDossiers(companyDossierResult.dossiers);
        setPlanExports(exports.exports); setPlanExportId(exports.exports.at(-1)?.export_id || '');
        setPlanPreviews(previews.previews); setPlanPreview(previews.previews.at(-1) || null);
        setPlanDecisions(decisions.decisions);
        setResumeArtifacts(artifacts.artifacts);
        const chosenArtifactId = artifacts.artifacts.some((item) => item.artifact_id === activeArtifactId)
          ? activeArtifactId : artifacts.artifacts.at(-1)?.artifact_id || '';
        setActiveArtifactId(chosenArtifactId);
        if (chosenArtifactId) await loadHandoffs(chosenArtifactId);
        else setHandoffs([]);
      }
      async function loadHandoffs(artifactId) {
        const result = await request(`/handoffs?artifact_id=${query(artifactId)}`);
        setHandoffs(result.handoffs);
      }
      async function prepareResearch(jobId) {
        const result = await post('/research/prepare', { batch_id: batch.batch_id, job_id: jobId });
        await loadM2(batch.batch_id);
        setNotice(`已保存岗位研究 ${jobId}：${result.research.status}。公司业务和投递渠道缺口请在批准方案前查看。`);
      }
      async function searchCompany(jobId) {
        const result = await post('/company/search', { batch_id: batch.batch_id, job_id: jobId });
        await loadM2(batch.batch_id);
        setNotice(`公司公开来源线索 ${result.search.lead_count} 条；请选择并抓取独立来源。`);
      }
      async function fetchCompany(discoveryId, sourceUrl) {
        const result = await post('/source/fetch', { discovery_id: discoveryId, source_url: sourceUrl });
        await loadM2(batch.batch_id);
        setNotice(`公司来源抓取：${result.fetch.content_state}；只有可读文本能提取摘录。`);
      }
      async function prepareCompany(jobId, discoveryId, captureId) {
        const result = await post('/company/prepare', { batch_id: batch.batch_id, job_id: jobId,
          discovery_id: discoveryId, capture_id: captureId });
        await loadM2(batch.batch_id);
        setNotice(`公司材料 ${result.company_dossier.company_dossier_id} r${result.company_dossier.revision} 已保存；来源权威性仍需核实。旧方案如输入变化需重新 G2。`);
      }
      async function preparePlan(jobId) {
        const result = await post('/plans/prepare', { batch_id: batch.batch_id, job_id: jobId });
        await loadM2(batch.batch_id);
        setNotice(`方案 ${result.plan.plan_id} r${result.plan.plan_revision} 已保存，等待 Owner G2 审阅。`);
      }
      async function downloadPlans() {
        const response = await fetch(`${API}/plans/workbook?batch_id=${query(batch.batch_id)}`, { cache: 'no-store' });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.error || `方案表下载失败：${response.status}`);
        }
        const id = response.headers.get('x-career-export-id');
        if (!id) throw new Error('Host 未返回方案 export_id');
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = url; link.download = `resume_tailoring_plans_${batch.batch_id}_${id}.xlsx`;
        document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        await loadM2(batch.batch_id);
        setPlanExportId(id);
        setNotice(`方案 XLSX 已导出：${id}。请在 Excel/WPS 审阅每岗参数并填写决定。`);
      }
      async function uploadPlans() {
        if (!planFile || !planExportId) throw new Error('请先选择方案导出版本和 XLSX 文件');
        const result = await request(`/plans/preview?export_id=${query(planExportId)}`, {
          method: 'POST', headers: { 'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
          body: planFile,
        });
        setPlanPreview(result.preview); setPlanPreviews((old) => [...old, result.preview]);
        setNotice('方案决定已回读并生成差异预览，尚未确认 G2。');
      }
      async function confirmG2() {
        const result = await post('/plans/confirm', { preview_id: planPreview.preview_id });
        await loadM2(batch.batch_id);
        setNotice(`G2 确认：应用 ${result.result.applied.length} 行，冲突 ${result.result.conflicts.length} 行。冲突行需重新导出审阅。`);
      }
      async function generateResume(planId) {
        const result = await post('/resumes/generate', { plan_id: planId });
        await loadM2(batch.batch_id);
        setActiveArtifactId(result.artifact.artifact_id);
        setNotice(`候选 PDF ${result.artifact.artifact_id}：${result.artifact.status}。只有 QA 合格并经本人 G3 审阅才可交付。`);
      }
      async function reviewResume(decision) {
        const artifact = resumeArtifacts.find((item) => item.artifact_id === activeArtifactId);
        if (!artifact) throw new Error('请先选择 PDF 候选');
        const result = await post('/resumes/review', {
          artifact_id: artifact.artifact_id, decision,
          reviewed_pdf_sha256: artifact.pdf_sha256,
          visual_checks: decision === 'APPROVE' ? g3Checks : null,
          owner_comment: decision === 'REQUEST_CHANGES' ? g3Comment : null,
        });
        await loadM2(batch.batch_id);
        setNotice(`G3 ${result.artifact.status}：${artifact.artifact_id}`);
      }
      async function exportHandoff() {
        const result = await post('/handoff/export', { artifact_id: activeArtifactId });
        await loadHandoffs(activeArtifactId);
        setNotice(`交接包 ${result.handoff.handoff_id} 已生成；面试研究状态仍为 NOT_STARTED。`);
      }
      async function searchSources() {
        const result = await post('/search-sources', { campaign_id: campaign.campaign_id });
        setSearch(result.search);
        await loadDiscoveries(result.search.discovery_id);
        setNotice('搜索仅得到来源线索，尚未抓取完整 JD 或生成合格候选岗位批次。');
      }
      async function loadDiscoveries(preferId = null) {
        const result = await request(`/discoveries?campaign_id=${query(campaign.campaign_id)}`);
        setDiscoveries(result.discoveries);
        const id = preferId || discovery?.discovery_id;
        const found = result.discoveries.find((item) => item.discovery_id === id) || null;
        setDiscovery(found);
        if (found) await loadNormalized(found.discovery_id);
        else { setNormalized([]); setSelectedNormalized([]); }
      }
      async function chooseDiscovery(id) {
        const found = discoveries.find((item) => item.discovery_id === id) || null;
        setDiscovery(found); setSelectedNormalized([]);
        if (found) await loadNormalized(id); else setNormalized([]);
      }
      async function loadNormalized(id) {
        const result = await request(`/normalized?discovery_id=${query(id)}`);
        setNormalized(result.normalized);
        setSelectedNormalized([]);
      }
      async function fetchLead(sourceUrl) {
        const result = await post('/source/fetch', { discovery_id: discovery.discovery_id, source_url: sourceUrl });
        await loadDiscoveries(discovery.discovery_id);
        setNotice(`Fetch ${result.fetch.content_state}；此时还不是合格岗位。`);
      }
      async function normalizeCapture(captureId) {
        const result = await post('/source/normalize', { discovery_id: discovery.discovery_id, capture_id: captureId });
        await loadNormalized(discovery.discovery_id);
        setNotice(`已标准化：${result.normalized.status}。请检查分类后逐个选择进入候选批次。`);
      }
      async function createBatch() {
        const result = await post('/batch/create', { discovery_id: discovery.discovery_id,
          normalized_ids: selectedNormalized });
        setNotice(`候选批次 ${result.batch.batch_id} 已创建；合格 ${result.batch.counts?.qualified ?? 0} / 目标 ${result.batch.target_count}。`);
        await loadBatches();
        await chooseBatch(result.batch.batch_id);
      }

      if (!state || !form) return h('main', { className: 'career-shell', 'data-career-v0-workbench': 'loading' },
        h('h1', null, 'Career 工作台'), h('p', null, error || '正在连接 Career Host…'));
      const p = form.project_inventory?.projects || [];
      const activeArtifact = resumeArtifacts.find((item) => item.artifact_id === activeArtifactId);
      return h('main', { className: 'career-shell', 'data-career-v0-workbench': 'ready' },
        h('style', null, `
          .career-shell{box-sizing:border-box;flex:1 1 auto;height:100%;min-height:0;overflow-y:auto;overflow-x:hidden;padding:28px 36px 80px;max-width:1100px;margin:0 auto;color:var(--fg,#20242b);font:14px/1.5 system-ui,sans-serif}
          .career-shell *{box-sizing:border-box}.career-shell h1{font-size:28px;margin:0}.career-shell h2{font-size:19px;margin:0 0 16px}
          .career-shell h3{font-size:15px;margin:0 0 12px}.career-shell p{margin:8px 0}.career-top{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:22px}
          .career-nav{display:flex;gap:6px;border-bottom:1px solid #ccd1d8;margin-bottom:18px}.career-nav button{border:0;border-bottom:3px solid transparent;border-radius:0;background:transparent}
          .career-nav button.active{border-color:#246bce;color:#174f9d}.career-panel{border:1px solid #d6dbe1;background:#fff;border-radius:10px;padding:20px;margin:16px 0}
          .career-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.career-field{display:flex;flex-direction:column;gap:5px;min-width:0}
          .career-field>span{font-weight:600}.career-field small{font-size:12px;color:#5e6673}.career-shell input,.career-shell select,.career-shell textarea{font:inherit;color:inherit;padding:7px 9px;border:1px solid #abb3bf;border-radius:6px;background:white;width:100%}
          .career-shell input[type=checkbox]{width:auto}.career-shell button{font:inherit;cursor:pointer;padding:7px 12px;border:1px solid #b9c5d5;border-radius:6px;background:#f4f7fb;color:#184775}
          .career-shell button:disabled{cursor:not-allowed;opacity:.45}.career-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0}
          .career-note{color:#596475}.career-alert{padding:10px 13px;border-radius:7px;margin:12px 0;background:#fff2dd;border:1px solid #dfb36b}
          .career-error{background:#ffebeb;border-color:#e2a2a2}.career-card{padding:14px;border:1px solid #dbe0e6;border-radius:8px;margin:10px 0}
          .career-meta{font-size:12px;color:#687282;word-break:break-all}.career-shell table{width:100%;border-collapse:collapse}.career-shell th,.career-shell td{border-bottom:1px solid #e0e4e8;padding:7px;text-align:left}
          @media(max-width:680px){.career-shell{padding:18px}.career-top{display:block}}
        `),
        h('header', { className: 'career-top' }, h('div', null,
          h('h1', null, 'Career 工作台'), h('p', { className: 'career-note' }, 'G0 偏好与项目清单 → M1 候选岗位表 → M2 方案审核 → M3 两页简历')),
        h('div', { className: 'career-meta' }, `Master SHA256: ${state.inventory.master_sha256}`)),
        h('nav', { className: 'career-nav' }, ...[['G0', 'G0 · 偏好确认'], ['M1', 'M1 · 岗位筛选'], ['M2', 'M2 · 方案审核'], ['M3', 'M3 · 简历审阅']].map(([key, label]) =>
          btn(label, () => setTab(key), false, { key, className: tab === key ? 'active' : '' }))),
        error && h('div', { className: 'career-alert career-error', role: 'alert' }, error),
        notice && h('div', { className: 'career-alert', role: 'status' }, notice),
        busy && h('p', { className: 'career-note' }, `${busy}…`),
        tab === 'G0' && h(React.Fragment, null,
          panel('Campaign', field('选择已有 Campaign 或新建草稿', choice(campaign?.campaign_id || '', chooseCampaign,
            state.campaigns.map((item) => [item.campaign_id, `${item.campaign_id} · ${item.status} · r${item.revision}`]))),
          h('p', { className: 'career-meta' }, campaign ? `当前：${campaign.campaign_id} · ${campaign.status} · r${campaign.revision}` : '尚未保存草稿')),
          panel('目标与边界',
            h('p', null, '固定基线：2027 届秋招校招；不启用实习岗位。确认 G0 时一并确认此约束。'),
            h('div', { className: 'career-grid' },
              field('目标岗位（逗号分隔）', input(form._roles_text, (v) => update((f) => { f._roles_text = v; }), '如：后端开发、平台工程')),
              field('城市范围', choice(form.city_scope.mode, (v) => update((f) => { f.city_scope.mode = v; }),
                [['ANY', '不限城市'], ['CITIES', '指定城市'], ['REMOTE', '仅远程']])),
              form.city_scope.mode === 'CITIES' && field('城市', input(form._cities_text, (v) => update((f) => { f._cities_text = v; }))),
              field('公司范围', choice(form.company_scope, (v) => update((f) => { f.company_scope = v; }),
                [['ANY', '不限公司'], ['FILTERED', '指定筛选']])),
              form.company_scope === 'FILTERED' && field('公司名称', input(form._company_names_text, (v) => update((f) => { f._company_names_text = v; }))),
              form.company_scope === 'FILTERED' && field('公司规模', input(form._company_sizes_text, (v) => update((f) => { f._company_sizes_text = v; }))),
              ...[['frontend', '前端相邻岗位'], ['algorithm', '算法相邻岗位'], ['sales', '销售相邻岗位']].map(([key, label]) =>
                field(label, choice(boolText(form.adjacent_role_policy[key]), (v) => update((f) => { f.adjacent_role_policy[key] = parseBool(v); }), yesNo))),
              field('税前月基本工资门槛（人民币）', input(form.salary.minimum ?? '', (v) => update((f) => { f.salary.minimum = v; }), '数字，0 表示不设最低额')),
              field('比较方式', choice(form.salary.comparison, (v) => update((f) => { f.salary.comparison = v; }), [['GTE', '大于等于'], ['GT', '严格大于']])),
              field('薪资未知', choice(form.salary.unknown_policy, (v) => update((f) => { f.salary.unknown_policy = v; }),
                [['REVIEW_BUCKET', '进入待核查池'], ['EXCLUDE', '排除']])),
              field('目标合格岗位数', input(form.batch_target_count, (v) => update((f) => { f.batch_target_count = v; }))),
            )),
          panel(`项目清单 · ${p.length} 个顶层项目`,
            h('p', { className: 'career-note' }, '逐一决定是否纳入；每个顶层候选都填写用途、核心技术栈和状态。每个子项目也需明确归属。当前默认不代选。'),
            ...p.map((project, index) => h('div', { className: 'career-card', key: project.project_id },
              h('h3', null, `${project.original_index}. ${project.name}`),
              h('div', { className: 'career-grid' },
                field('是否纳入', choice(boolText(project.include_in_resume), (v) => update((f) => { f.project_inventory.projects[index].include_in_resume = parseBool(v); }),
                  [['true', '纳入'], ['false', '不纳入']])),
                field('用途', input(project.purpose || '', (v) => update((f) => { f.project_inventory.projects[index].purpose = v; }))),
                field('核心技术栈（逗号分隔）', input(project._stack_text || '', (v) => update((f) => { f.project_inventory.projects[index]._stack_text = v; }))),
                field('状态', choice(project.status || '', (v) => update((f) => { f.project_inventory.projects[index].status = v; }),
                  [['COMPLETED', '已完成'], ['PARTIALLY_VERIFIED', '部分验证'], ['IN_PROGRESS', '进行中'], ['EXPLORING', '探索中']])),
              ),
              ...(project.child_candidates || []).map((child, childIndex) => field(`子项目：${child.name}`,
                choice(child.owner_decision || '', (v) => update((f) => { f.project_inventory.projects[index].child_candidates[childIndex].owner_decision = v; }),
                  [['SUBPROJECT', '归属此项目'], ['INDEPENDENT', '独立项目'], ['OUT_OF_SCOPE', '不纳入']])))
            ))),
          panel('核心身份信号 · 三项都需本人确认',
            h('p', { className: 'career-note' }, '从当前 Master 中逐字复制原文，并单独填写获准表达；不要用页面自动猜测或默认勾选。'),
            btn(masterText === null ? '查看 Master 原文' : '重新读取 Master', () => run('读取 Master', loadMaster), !!busy),
            masterText !== null && field('当前 Master 原文（只读）',
              h('textarea', { readOnly: true, rows: 14, value: masterText, style: { marginTop: 8 } })),
            ...['ID-PLATFORMS', 'ID-PROJECTS', 'ID-PROVENANCE'].map((id) => {
              const signal = form.identity_signals[id] || {};
              return h('div', { className: 'career-card', key: id }, h('h3', null, id),
                h('div', { className: 'career-grid' },
                  field('Master 原文摘录（需逐字匹配）', input(signal.source_quote || '', (v) => update((f) => { f.identity_signals[id].source_quote = v; }))),
                  field('批准的表达', input(signal.approved_expression || '', (v) => update((f) => { f.identity_signals[id].approved_expression = v; })))),
                h('label', null, h('input', { type: 'checkbox', checked: signal.owner_confirmed === true,
                  onChange: (event) => update((f) => { f.identity_signals[id].owner_confirmed = event.target.checked; }) }),
                  ' 我本人确认此原文与表达'));
            })),
          h('div', { className: 'career-actions' },
            btn(campaign ? '保存修订草稿' : '保存新草稿', () => run('保存草稿', saveDraft), !!busy),
            btn('本人确认 G0', () => run('确认 G0', confirmG0), !!busy || !campaign || dirty || campaign.status === 'PREFERENCE_CONFIRMED'),
            h('span', { className: 'career-note' }, dirty ? '表单有未保存更改；请先保存草稿。' : '确认操作独立于保存草稿。')),
        ),
        tab === 'M1' && h(React.Fragment, null,
          panel('来源搜索与真实进度',
            h('p', null, campaign?.status === 'PREFERENCE_CONFIRMED'
              ? `已确认 Campaign ${campaign.campaign_id} · r${campaign.revision}` : '先完成 G0 确认，才能搜索岗位来源。'),
            h('p', { className: 'career-note' }, '当前 DSH 搜索仅收集来源线索。还需要逐条抓取完整 JD、核实在招与待遇、筛出合格岗位并创建批次。线索数量不能当作合格岗位数量。'),
            h('div', { className: 'career-actions' },
              btn('搜索来源线索', () => run('搜索来源线索', searchSources), !!busy || campaign?.status !== 'PREFERENCE_CONFIRMED'),
              btn('刷新来源记录', () => run('读取来源', () => loadDiscoveries()), !!busy || campaign?.status !== 'PREFERENCE_CONFIRMED'),
              btn('刷新候选批次', () => run('读取批次', loadBatches), !!busy || campaign?.status !== 'PREFERENCE_CONFIRMED')),
            search && h('p', { className: 'career-meta' }, `本次搜索：${search.discovery_id} · 来源线索 ${search.lead_count} · 已确认合格岗位 ${search.qualified_job_count}`),
            field('来源记录', choice(discovery?.discovery_id || '', (v) => run('读取来源', () => chooseDiscovery(v)),
              discoveries.map((item) => [item.discovery_id, `${item.discovery_id} · ${item.leads.length} 条线索 · r${item.revision}`]))),
            discovery && h(React.Fragment, null,
              h('h3', null, `来源线索 ${discovery.leads.length} 条`),
              ...discovery.leads.map((lead) => h('div', { className: 'career-card', key: lead.source_url },
                h('p', null, lead.title_hint || '未命名来源'),
                h('p', { className: 'career-meta' }, lead.source_url),
                btn('抓取该来源', () => run('抓取来源', () => fetchLead(lead.source_url)), !!busy))),
              h('h3', null, `抓取结果 ${discovery.captures.length} 条`),
              ...discovery.captures.map((capture) => h('div', { className: 'career-card', key: capture.capture_id },
                h('p', null, `${capture.content_state} · HTTP ${capture.http_status ?? '未知'}`),
                h('p', { className: 'career-meta' }, capture.source_url),
                btn('标准化此抓取', () => run('标准化来源', () => normalizeCapture(capture.capture_id)),
                  !!busy || capture.content_state !== 'FETCHED_TEXT'))),
              h('h3', null, `标准化记录 ${normalized.length} 条`),
              ...normalized.map((item) => h('div', { className: 'career-card', key: item.normalized_id },
                h('p', null, `${item.classified?.company || '公司未知'} · ${item.classified?.title || '岗位未知'} · ${item.classified?.pool || item.status}`),
                h('p', { className: 'career-meta' }, `${item.normalized_id} · ${item.source_url}`),
                h('p', { className: 'career-meta' }, (item.classified?.risk_flags || []).join('、')),
                item.status === 'CLASSIFIED_CANDIDATE' && h('label', null,
                  h('input', { type: 'checkbox', checked: selectedNormalized.includes(item.normalized_id),
                    onChange: (event) => setSelectedNormalized((old) => event.target.checked
                      ? [...old, item.normalized_id] : old.filter((id) => id !== item.normalized_id)) }),
                  ' 选择进入候选批次'))),
              btn(`创建候选批次（已选 ${selectedNormalized.length}）`, () => run('创建批次', createBatch),
                !!busy || !selectedNormalized.length),
            )),
          panel('候选批次与 Excel 回读',
            field('批次', choice(batch?.batch_id || '', (v) => run('读取批次', () => chooseBatch(v)),
              batches.map((item) => [item.batch_id, `${item.batch_id} · 合格 ${item.counts?.qualified ?? 0} / 目标 ${item.target_count}`]))),
            !batch && h('p', { className: 'career-note' }, '当前没有选中的候选批次，不能导出或确认。'),
            batch && h(React.Fragment, null,
              h('p', null, `合格 ${batch.counts?.qualified ?? 0} · 待核查 ${batch.counts?.unknown ?? 0} · 排除 ${batch.counts?.excluded ?? 0} · 缺口 ${batch.target_shortfall ?? '—'}`),
              h('div', { className: 'career-actions' }, btn('导出候选 XLSX', () => run('导出 XLSX', download), !!busy || !batch.counts?.qualified)),
              field('对应的导出版本', choice(exportId, (v) => { setExportId(v); setPreview(null); },
                exports.map((item) => [item.export_id, `${item.export_id} · batch r${item.batch_revision}`]))),
              field('上传本人回填的 XLSX', h('input', { type: 'file', accept: '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                onChange: (event) => { setFile(event.target.files?.[0] || null); setPreview(null); } })),
              h('div', { className: 'career-actions' }, btn('回读并预览（不确认）', () => run('回读 XLSX', upload), !!busy || !file || !exportId)),
              field('已保存的回读预览（刷新后可恢复）', choice(preview?.preview_id || '', (v) => {
                setPreview(previews.find((item) => item.preview_id === v) || null); setAcceptShortfall(false);
              }, previews.map((item) => [item.preview_id,
                `${item.preview_id} · 选中 ${item.selected_job_ids?.length ?? 0} · ${item.created_at}`]))),
              selection && h('p', { className: 'career-alert' }, `已确认选择：${selection.selection_id}，${selection.selected_job_ids?.length ?? 0} 个岗位。`),
              preview && h('div', { className: 'career-card' },
                h('h3', null, '回读预览，等待本人确认 G1'),
                h('p', null, `预览版本 ${preview.preview_id} · 选中 ${preview.selected_job_ids?.length ?? 0} 个岗位`),
                !!batch.target_shortfall && h('label', null,
                  h('input', { type: 'checkbox', checked: acceptShortfall,
                    onChange: (event) => setAcceptShortfall(event.target.checked) }),
                  ` 我本人接受本批合格岗位 ${batch.counts?.qualified ?? 0} / 目标 ${batch.target_count}，缺口 ${batch.target_shortfall}`),
                h('p', { className: 'career-meta' }, `文件 SHA256：${preview.file_sha256}`),
                h('pre', { className: 'career-meta' }, JSON.stringify({ selected_job_ids: preview.selected_job_ids,
                  owner_priority: preview.owner_priority, owner_note: preview.owner_note }, null, 2)),
                btn('本人确认 G1 选岗', () => run('确认 G1', confirmG1), !!busy || !preview.selected_job_ids?.length ||
                  (!!batch.target_shortfall && !acceptShortfall))),
            )),
        ),
        tab === 'M2' && h(React.Fragment, null,
          panel('已选岗位研究与逐岗方案',
            !selection && h('p', { className: 'career-alert' }, '先在 M1 上传候选 XLSX 并本人确认 G1；未选岗位不能进入研究或拟方案。'),
            selection && h('p', null, `G1 ${selection.selection_id} · 已选 ${selectedJobs.length} 个岗位。研究和方案只针对这些岗位。`),
            selection && h('div', { className: 'career-actions' },
              btn('刷新研究与方案', () => run('刷新 M2', () => loadM2(batch.batch_id)), !!busy)),
            ...selectedJobs.map((job) => {
              const research = researchRows.find((row) => row.job_id === job.job_id);
              const companyDossier = companyDossiers.find((row) => row.company === job.company);
              const sourceGroups = companySources.filter((row) => row.company === job.company);
              const stored = planRows.find((row) => row.job_id === job.job_id);
              const researchChanged = !!stored && !!research &&
                stored.plan?.input_refs?.research_revision !== research.revision;
              const decision = planDecisions.find((row) => row.plan_id === stored?.plan_id);
              const g3ChangeRequest = resumeArtifacts.some((item) => item.plan_id === stored?.plan_id &&
                item.plan_revision === stored?.revision && item.status === 'OWNER_REQUESTED_CHANGES');
              return h('div', { className: 'career-card', key: job.job_id },
                h('h3', null, `${job.company} · ${job.title}`),
                h('p', { className: 'career-meta' }, `${job.job_id} · ${job.source_url}`),
                h('p', null, `JD：${job.jd_completeness || '未核实'} · 研究：${research?.status || '未建立'} · 方案：${stored ? `${stored.plan_id} r${stored.revision}` : '未建立'}`),
                !job.source_capture_id && h('p', { className: 'career-alert' },
                  '没有绑定可核对的 DSH Fetch 完整 JD；不能从 FULL 标记直接建立岗位研究。'),
                research && h('div', null,
                  h('p', null, research.business_summary),
                  h('p', { className: 'career-alert' }, `公司业务范围：${research.business_scope_status || '需核实'}；投递：${research.application_card?.application_status || '未知'}。${(research.unknowns || []).join('；')}`),
                  h('p', { className: 'career-meta' }, `JD SHA256 ${research.jd?.sha256} · 来源 ${research.jd?.source_url}`)),
                companyDossier && h('p', { className: 'career-meta' },
                  `同公司材料 ${companyDossier.company_dossier_id} r${companyDossier.revision} · ${companyDossier.source_url} · 抓取 ${companyDossier.captured_at} · 来源权威性 ${companyDossier.source_authority}`),
                h('details', null, h('summary', null, '独立公司公开来源与复用'),
                  h('p', { className: 'career-note' }, '只对 G1 已选公司的公开来源做研究。需先搜索，再选择链接抓取；引用必须逐字出现在抓取正文。来源权威性、时效及投递渠道仍需核实。'),
                  btn('搜索该公司公开来源', () => run('搜索公司来源', () => searchCompany(job.job_id)), !!busy),
                  ...sourceGroups.map((source) => h('div', { className: 'career-card', key: source.discovery_id },
                    h('p', null, `${source.discovery_id} · ${source.leads.length} 条线索`),
                    ...source.leads.map((lead) => h('p', { key: lead.source_url },
                      h('a', { href: lead.source_url, target: '_blank', rel: 'noopener noreferrer' },
                        `${lead.title_hint} · ${lead.source_url}`),
                      ' ', btn('抓取', () => run('抓取公司来源', () => fetchCompany(source.discovery_id, lead.source_url)), !!busy))),
                    ...source.captures.map((capture) => h('p', { key: capture.capture_id },
                      `${capture.content_state} · ${capture.source_url} · ${capture.captured_at} `,
                      btn('提取并引用公司摘录', () => run('提取公司材料', () =>
                        prepareCompany(job.job_id, source.discovery_id, capture.capture_id)),
                      !!busy || capture.content_state !== 'FETCHED_TEXT')))))),
                researchChanged && h('p', { className: 'career-alert' }, '公司研究输入已更新；当前方案与旧 G2 决定失效，请拟新方案并重新审表。'),
                stored && h('div', null,
                  h('p', null, `策略：${stored.plan?.strategy?.summary || '未提供'}`),
                  h('p', null, `HERO：${(stored.plan?.project_plan || []).filter((row) => row.tier === 'HERO').map((row) => row.project_id).join('、')}`),
                  h('p', null, `COMPACT：${(stored.plan?.project_plan || []).filter((row) => row.tier === 'COMPACT').map((row) => row.project_id).join('、')}`),
                  h('p', null, `版式：${stored.plan?.layout_plan?.template_id} · ${stored.plan?.layout_plan?.font_size_pt}pt · ${stored.plan?.layout_plan?.target_pages} 页 A4`),
                  h('p', { className: 'career-meta' }, `方案 SHA256 ${stored.validation?.plan_content_sha256} · 输入 SHA256 ${stored.validation?.input_snapshot_sha256}`),
                  h('p', { className: 'career-meta' }, `风险：${JSON.stringify(stored.plan?.risks || [])}`),
                  h('p', null, `Owner 决定：${decision ? `${decision.decision} (r${decision.plan_revision})` : 'PENDING'}`),
                  h('details', null, h('summary', null, '查看逐项目参数与保留信号'),
                    h('table', null, h('thead', null, h('tr', null,
                      ...['原序', '项目', '层级', '目标', '原因与强调'].map((title) => h('th', { key: title }, title)))),
                    h('tbody', null, ...(stored.plan?.project_plan || []).map((row) => h('tr', { key: row.project_id },
                      h('td', null, row.source_order), h('td', null, row.project_id), h('td', null, row.tier),
                      h('td', null, row.tier === 'HERO' ? `${row.target_bullets} bullet` : `${row.target_lines} 行`),
                      h('td', null, `${row.rationale || ''}；${(row.emphasis || []).join('、')}`))))),
                    h('p', null, `保护信号：${Object.entries(stored.plan?.protected_signal_plan || {}).map(([key, row]) => `${key} ${row.handling}`).join('；')}`),
                    h('p', null, `实习/section：${(stored.plan?.section_plan || []).map((row) => `${row.section_id} ${row.action} ${row.rationale}`).join('；')}`))),
                h('div', { className: 'career-actions' },
                  btn('从已选完整 JD 建研究底稿', () => run('准备研究', () => prepareResearch(job.job_id)),
                    !!busy || !!research || job.jd_completeness !== 'FULL' || !job.source_capture_id),
                  btn(decision?.decision === 'REQUEST_CHANGES' || g3ChangeRequest ? '按退回意见拟新版本' : '拟逐岗修改方案',
                    () => run('拟方案', () => preparePlan(job.job_id)),
                    !!busy || research?.status !== 'READY_FOR_PLAN' ||
                    (!!stored && decision?.decision !== 'REQUEST_CHANGES' && !g3ChangeRequest && !researchChanged))));
            })),
          panel('方案 XLSX 预审与 G2',
            h('p', { className: 'career-note' }, '先审方案参数，再在 Excel/WPS 填 PENDING / APPROVE / REQUEST_CHANGES / SKIP。上传只生成差异预览；本人再次点击确认才登记 G2。批准绑定当前方案与输入 SHA256。'),
            h('div', { className: 'career-actions' },
              btn('导出方案 XLSX', () => run('导出方案表', downloadPlans), !!busy || !planRows.length)),
            field('方案导出版本', choice(planExportId, (v) => { setPlanExportId(v); setPlanPreview(null); },
              planExports.map((item) => [item.export_id, item.export_id]))),
            field('上传本人回填的方案 XLSX', h('input', { type: 'file',
              accept: '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
              onChange: (event) => { setPlanFile(event.target.files?.[0] || null); setPlanPreview(null); } })),
            h('div', { className: 'career-actions' },
              btn('回读方案决定并预览', () => run('回读方案表', uploadPlans), !!busy || !planFile || !planExportId)),
            field('已保存的方案预览', choice(planPreview?.preview_id || '',
              (v) => setPlanPreview(planPreviews.find((item) => item.preview_id === v) || null),
              planPreviews.map((item) => [item.preview_id, `${item.preview_id} · ${item.created_at}`]))),
            planPreview && h('div', { className: 'career-card' },
              h('h3', null, `待确认：${planPreview.preview_id}`),
              h('p', null, `可处理决定 ${planPreview.valid_rows?.filter((row) => row.decision !== 'PENDING').length || 0} 项；冲突 ${planPreview.conflicts?.length || 0} 项。`),
              ...(planPreview.valid_rows || []).map((row) => h('p', { key: row.plan_id },
                `${row.plan_id} r${row.plan_revision} → ${row.decision}${row.owner_comment ? `；意见：${row.owner_comment}` : ''}`)),
              ...(planPreview.conflicts || []).map((row) => h('p', { className: 'career-alert', key: row.plan_id },
                `${row.plan_id} 冲突：${row.reason}`)),
              btn('本人确认 G2 决定', () => run('确认 G2', confirmG2),
                !!busy || !(planPreview.valid_rows || []).some((row) => row.decision !== 'PENDING')))),
        ),
        tab === 'M3' && h(React.Fragment, null,
          panel('仅为有效 G2 批准生成候选 PDF',
            !selection && h('p', { className: 'career-alert' }, '尚无 G1 选岗；不能生成简历。'),
            h('p', { className: 'career-note' }, 'Host 在实际渲染前重新核对方案 revision、方案内容哈希、输入快照和 G2 决定。页数、项目覆盖或文字检查失败时显示冲突并返回 G2；不会自动改成三页或删除项目。'),
            ...planRows.map((stored) => {
              const decision = planDecisions.find((row) => row.plan_id === stored.plan_id);
              const already = resumeArtifacts.some((item) => item.plan_id === stored.plan_id &&
                item.plan_revision === stored.revision);
              return h('div', { className: 'career-card', key: stored.plan_id },
                h('h3', null, `${stored.plan_id} r${stored.revision}`),
                h('p', null, `G2：${decision?.decision || 'PENDING'} · 岗位 ${stored.job_id}`),
                btn('生成该获批方案的候选 PDF', () => run('生成 PDF', () => generateResume(stored.plan_id)),
                  !!busy || decision?.decision !== 'APPROVE' || decision?.plan_revision !== stored.revision || already));
            })),
          panel('PDF 预览与 G3 本人审阅',
            field('候选产物', choice(activeArtifactId, (v) => {
              setActiveArtifactId(v); setG3Checks({ both_pages_readable: false,
                no_clipping_or_overlap: false, all_projects_visible: false }); setG3Comment('');
              if (v) run('读取交接包', () => loadHandoffs(v)); else setHandoffs([]);
            }, resumeArtifacts.map((item) => [item.artifact_id, `${item.artifact_id} · ${item.status}`]))),
            activeArtifact && h(React.Fragment, null,
              h('p', null, `状态：${activeArtifact.status} · QA 页数 ${activeArtifact.qa?.page_count} · HERO ${activeArtifact.qa?.hero_count}`),
              h('p', { className: 'career-meta' }, `PDF SHA256 ${activeArtifact.pdf_sha256} · 方案 ${activeArtifact.plan_id} r${activeArtifact.plan_revision} · 输入 ${activeArtifact.input_snapshot_sha256}`),
              (activeArtifact.qa?.problems || []).length > 0 && h('p', { className: 'career-alert' },
                `QA 未通过：${activeArtifact.qa.problems.join('、')}。需要回 G2 审阅取舍；本产物不能 G3 批准。`),
              h('iframe', { title: `PDF ${activeArtifact.artifact_id}`,
                src: `${API}/resumes/pdf?artifact_id=${query(activeArtifact.artifact_id)}`,
                style: { width: '100%', height: '680px', border: '1px solid #cbd3db' } }),
              h('h3', null, '逐页渲染图像'),
              ...(activeArtifact.qa?.page_image_paths || []).map((_, index) => h('div',
                { className: 'career-card', key: `page-${index + 1}` },
                h('p', null, `第 ${index + 1} 页`),
                h('img', { src: `${API}/resumes/page-image?artifact_id=${query(activeArtifact.artifact_id)}&page=${index + 1}`,
                  alt: `${activeArtifact.artifact_id} 第 ${index + 1} 页渲染图像`,
                  style: { display: 'block', maxWidth: '100%', border: '1px solid #cbd3db' } }))),
              h('p', null, h('a', { href: `${API}/resumes/pdf?artifact_id=${query(activeArtifact.artifact_id)}`,
                target: '_blank', rel: 'noopener noreferrer' }, '在新窗口打开 PDF')),
              activeArtifact.status === 'WAITING_VISUAL_REVIEW' && h('div', { className: 'career-card' },
                h('h3', null, 'G3 视觉与内容确认'),
                ...[
                  ['both_pages_readable', '我已逐页查看，两页 A4 均可读'],
                  ['no_clipping_or_overlap', '我已检查，没有裁切、遮挡或乱码'],
                  ['all_projects_visible', '我已检查完整项目集合和核心身份信号'],
                ].map(([key, label]) => h('label', { key, style: { display: 'block', margin: '7px 0' } },
                  h('input', { type: 'checkbox', checked: g3Checks[key],
                    onChange: (event) => setG3Checks((old) => ({ ...old, [key]: event.target.checked })) }),
                  ` ${label}`)),
                btn('本人确认 G3 成品', () => run('确认 G3', () => reviewResume('APPROVE')),
                  !!busy || (activeArtifact.qa?.page_image_paths || []).length !== 2 ||
                  !Object.values(g3Checks).every(Boolean))),
              !activeArtifact.owner_review && h('div', { className: 'career-card' },
                field('要求修订的具体原因', h('textarea', { rows: 3, value: g3Comment,
                  onChange: (event) => setG3Comment(event.target.value) })),
                btn('本人退回此 PDF', () => run('退回 PDF', () => reviewResume('REQUEST_CHANGES')),
                  !!busy || !g3Comment.trim())))),
          panel('投递与面试研究交接',
            h('p', { className: 'career-note' }, '只有 G3 已批准且输入仍有效的版本可导出。交接包包含 Job Card、Application Card、完整 JD、公司研究、PDF/可读文本和研究提示。用户自行投递或交给外部研究 Agent；包就绪不等于面试研究完成。'),
            activeArtifact && h('p', null, `当前投递状态：${researchRows.find((row) => row.job_id === activeArtifact.job_id)?.application_card?.application_status || '未知'}`),
            btn('生成交接 ZIP', () => run('生成交接包', exportHandoff),
              !!busy || activeArtifact?.status !== 'OWNER_APPROVED'),
            ...handoffs.map((item) => h('p', { key: item.handoff_id },
              h('a', { href: `${API}/handoff/zip?handoff_id=${query(item.handoff_id)}` },
                `下载 ${item.handoff_id}.zip`),
              ` · ${item.status} · 面试研究 ${item.interview_research_status}`))),
        ),
      );
    }

    function Glyph({ size }) {
      return h('span', { 'aria-hidden': 'true', style: { fontSize: size || 18, fontWeight: 800, lineHeight: 1 } }, 'C');
    }
    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'career-v0' }, CareerWorkbench));
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: 'career-v0', order: 70, label: 'Career 工作台',
        }, Glyph));
      },
    };
  },
});
