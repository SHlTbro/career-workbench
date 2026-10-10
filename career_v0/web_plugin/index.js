import { spawn } from 'node:child_process';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { mkdir, readFile, stat, writeFile, unlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const inject = ['connection'];

const projectRoot = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const MAX_JSON = 2 * 1024 * 1024;
const MAX_XLSX = 10 * 1024 * 1024;

function errorResponse(message, status = 400) {
  return Response.json({ ok: false, error: message }, {
    status,
    headers: { 'cache-control': 'no-store' },
  });
}

async function boundedBody(request, limit) {
  const chunks = [];
  let size = 0;
  if (request.body) {
    for await (const chunk of request.body) {
      size += chunk.byteLength;
      if (size > limit) throw Object.assign(new Error(`request exceeds ${limit} bytes`), { status: 413 });
      chunks.push(Buffer.from(chunk));
    }
  }
  return Buffer.concat(chunks);
}

async function jsonBody(request) {
  if (request.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() !== 'application/json') {
    throw Object.assign(new Error('Content-Type must be application/json'), { status: 415 });
  }
  const raw = await boundedBody(request, MAX_JSON);
  let value;
  try { value = JSON.parse(raw.toString('utf8')); }
  catch { throw Object.assign(new Error('invalid JSON body'), { status: 400 }); }
  if (!value || Array.isArray(value) || typeof value !== 'object') {
    throw Object.assign(new Error('JSON body must be an object'), { status: 400 });
  }
  return value;
}

function requireId(value, name) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(value)) {
    throw Object.assign(new Error(`${name} is missing or invalid`), { status: 400 });
  }
  return value;
}

function requiredConfiguration() {
  const state = process.env.CAREER_STATE_DIR;
  const master = process.env.CAREER_MASTER_PATH;
  if (!state || !master) {
    throw Object.assign(new Error('Career Host state/master paths are not configured'), { status: 503 });
  }
  return { state: path.resolve(state), master: path.resolve(master) };
}

// Interpreter for the bridge subprocess. The Host launcher sets CAREER_PYTHON to
// the project's pinned Python; when absent we fall back to the PATH-resolved
// 'python'. A configured value must be an absolute executable path.
function pythonBinary() {
  const configured = process.env.CAREER_PYTHON;
  if (!configured) return 'python';
  const resolved = path.resolve(configured);
  if (!path.isAbsolute(resolved)) {
    throw Object.assign(new Error('CAREER_PYTHON must be an absolute executable path'), { status: 500 });
  }
  return resolved;
}

function runBridge(op, fields, ownerSecret, config) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBinary(), ['-m', 'career_v0.bridge'], {
      cwd: process.env.CAREER_PROJECT_ROOT || projectRoot,
      windowsHide: true,
      env: {
        ...process.env,
        CAREER_STATE_DIR: config.state,
        CAREER_MASTER_PATH: config.master,
        CAREER_OWNER_ACTION_SECRET: ownerSecret,
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const output = [];
    const errors = [];
    let outputSize = 0;
    const timer = setTimeout(() => child.kill(),
      ['search_sources', 'search_company_sources', 'prepare_tailoring_plan'].includes(op) ? 360000 :
      op === 'generate_resume_candidate' ? 110000 :
      ['fetch_source', 'normalize_source', 'prepare_company_dossier'].includes(op) ? 240000 : 30000);
    child.stdout.on('data', (chunk) => {
      outputSize += chunk.length;
      if (outputSize > 8 * 1024 * 1024) child.kill();
      else output.push(chunk);
    });
    child.stderr.on('data', (chunk) => errors.push(chunk));
    child.on('error', (error) => { clearTimeout(timer); reject(error); });
    child.on('close', (code) => {
      clearTimeout(timer);
      let envelope;
      try { envelope = JSON.parse(Buffer.concat(output).toString('utf8')); }
      catch { return reject(new Error(`Career bridge failed (${code}): ${Buffer.concat(errors).toString('utf8').slice(0, 300)}`)); }
      if (!envelope.ok) {
        const error = new Error(envelope.error || 'Career bridge rejected operation');
        error.status = /stale|revision|changed after/i.test(error.message) ? 409 : 422;
        return reject(error);
      }
      resolve(envelope.result);
    });
    child.stdin.end(JSON.stringify({ op, ...fields }));
  });
}

function artifactPath(config, value, folder) {
  const root = path.resolve(config.state, 'artifacts', folder);
  const target = path.resolve(String(value || ''));
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw Object.assign(new Error('Career artifact escaped its expected folder'), { status: 500 });
  }
  return target;
}

export function apply(ctx) {
  // The secret is created inside this Host plugin and passed only to its bridge child.
  // No browser field, model text, or workbook value can supply actor_channel.
  const ownerSecret = randomBytes(32).toString('hex');
  const bridge = (op, fields = {}) => runBridge(op, fields, ownerSecret, requiredConfiguration());
  const routes = [
    ['/api/career-v0/state', 'GET', async () => {
      const [inventory, campaigns] = await Promise.all([
        bridge('inventory_candidate'), bridge('list_campaigns'),
      ]);
      return Response.json({ ok: true, inventory, campaigns: campaigns.campaigns }, { headers: { 'cache-control': 'no-store' } });
    }],
    ['/api/career-v0/master', 'GET', async () => {
      const config = requiredConfiguration();
      if ((await stat(config.master)).size > MAX_JSON) {
        throw Object.assign(new Error('master file is too large to preview in Web'), { status: 413 });
      }
      return new Response(await readFile(config.master), {
        headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' },
      });
    }],
    ['/api/career-v0/campaign/draft', 'POST', async (request) => {
      const { preferences } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('create_campaign', { preferences })) });
    }],
    ['/api/career-v0/campaign/revise', 'POST', async (request) => {
      const { campaign_id, preferences } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('revise_campaign', {
        campaign_id: requireId(campaign_id, 'campaign_id'), preferences,
      })) });
    }],
    ['/api/career-v0/campaign/confirm', 'POST', async (request) => {
      const { campaign_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('confirm_campaign', {
        campaign_id: requireId(campaign_id, 'campaign_id'),
      })) });
    }],
    ['/api/career-v0/batches', 'GET', async (request) => {
      const campaign_id = requireId(new URL(request.url).searchParams.get('campaign_id'), 'campaign_id');
      return Response.json({ ok: true, ...(await bridge('list_batches', { campaign_id })) });
    }],
    ['/api/career-v0/search-sources', 'POST', async (request) => {
      const { campaign_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('search_sources', {
        campaign_id: requireId(campaign_id, 'campaign_id'),
      })) });
    }],
    ['/api/career-v0/discoveries', 'GET', async (request) => {
      const campaign_id = requireId(new URL(request.url).searchParams.get('campaign_id'), 'campaign_id');
      const result = await bridge('list_discoveries', { campaign_id });
      return Response.json({ ok: true, discoveries: result.discoveries.map((record) => ({
        discovery_id: record.discovery_id, revision: record.revision,
        campaign_id: record.campaign_id, campaign_revision: record.campaign_revision,
        leads: record.leads, captures: record.captures.map((capture) => ({
          capture_id: capture.capture_id, source_url: capture.source_url,
          http_status: capture.http_status, content_state: capture.content_state,
        })),
      })) });
    }],
    ['/api/career-v0/source/fetch', 'POST', async (request) => {
      const { discovery_id, source_url } = await jsonBody(request);
      if (typeof source_url !== 'string' || !/^https?:\/\//i.test(source_url) || source_url.length > 4000) {
        throw Object.assign(new Error('source_url invalid'), { status: 400 });
      }
      return Response.json({ ok: true, ...(await bridge('fetch_source', {
        discovery_id: requireId(discovery_id, 'discovery_id'), source_url,
      })) });
    }],
    ['/api/career-v0/source/normalize', 'POST', async (request) => {
      const { discovery_id, capture_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('normalize_source', {
        discovery_id: requireId(discovery_id, 'discovery_id'),
        capture_id: requireId(capture_id, 'capture_id'),
      })) });
    }],
    ['/api/career-v0/normalized', 'GET', async (request) => {
      const discovery_id = requireId(new URL(request.url).searchParams.get('discovery_id'), 'discovery_id');
      const result = await bridge('list_normalized_sources', { discovery_id });
      return Response.json({ ok: true, normalized: result.normalized.map((item) => ({
        normalized_id: item.normalized_id, source_url: item.source_url, status: item.status,
        discovery_revision: item.discovery_revision, classified: item.classified && {
          company: item.classified.company, title: item.classified.title,
          pool: item.classified.pool, risk_flags: item.classified.risk_flags,
        },
      })) });
    }],
    ['/api/career-v0/batch/create', 'POST', async (request) => {
      const { discovery_id, normalized_ids } = await jsonBody(request);
      if (!Array.isArray(normalized_ids) || !normalized_ids.length || normalized_ids.length > 500) {
        throw Object.assign(new Error('select normalized source IDs'), { status: 400 });
      }
      return Response.json({ ok: true, ...(await bridge('create_batch_from_normalizations', {
        discovery_id: requireId(discovery_id, 'discovery_id'),
        normalized_ids: normalized_ids.map((id) => requireId(id, 'normalized_id')),
      })) });
    }],
    ['/api/career-v0/batch', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('get_batch', { batch_id })) });
    }],
    ['/api/career-v0/candidate-exports', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_candidate_exports', { batch_id })) });
    }],
    ['/api/career-v0/selection', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('get_selection', { batch_id })) });
    }],
    ['/api/career-v0/selection-previews', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      const result = await bridge('list_selection_previews', { batch_id });
      return Response.json({ ok: true, previews: result.previews.map((item) => ({
        preview_id: item.preview_id, batch_id: item.batch_id,
        export_id: item.export_id, created_at: item.created_at,
        file_sha256: item.file_sha256, selected_job_ids: item.selected_job_ids,
        added_job_ids: item.added_job_ids, removed_job_ids: item.removed_job_ids,
        owner_priority: item.owner_priority, owner_note: item.owner_note,
        status: item.status,
      })) });
    }],
    ['/api/career-v0/candidates/workbook', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      const config = requiredConfiguration();
      const result = await bridge('export_candidates', { batch_id });
      const target = artifactPath(config, result.artifact_path, 'exports');
      return new Response(await readFile(target), {
        headers: {
          'content-type': XLSX_MIME,
          'content-disposition': `attachment; filename="${path.basename(target)}"`,
          'x-career-export-id': result.snapshot.export_id,
          'cache-control': 'no-store',
        },
      });
    }],
    ['/api/career-v0/candidates/preview', 'POST', async (request) => {
      const export_id = requireId(new URL(request.url).searchParams.get('export_id'), 'export_id');
      if (request.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() !== XLSX_MIME) {
        throw Object.assign(new Error('expected XLSX upload'), { status: 415 });
      }
      const config = requiredConfiguration();
      const bytes = await boundedBody(request, MAX_XLSX);
      const folder = path.join(config.state, '_uploads');
      await mkdir(folder, { recursive: true });
      const uploadPath = path.join(folder, `upload-${randomUUID()}.xlsx`);
      await writeFile(uploadPath, bytes, { flag: 'wx' });
      try { return Response.json({ ok: true, ...(await bridge('preview_selection', { export_id, upload_path: uploadPath })) }); }
      finally { await unlink(uploadPath).catch(() => {}); }
    }],
    ['/api/career-v0/candidates/confirm', 'POST', async (request) => {
      const { preview_id, accept_shortfall } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('confirm_selection', {
        preview_id: requireId(preview_id, 'preview_id'),
        accept_shortfall: accept_shortfall === true,
      })) });
    }],
    ['/api/career-v0/selected-jobs', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('selected_jobs', { batch_id })) });
    }],
    ['/api/career-v0/company-sources', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      const result = await bridge('list_company_sources', { batch_id });
      return Response.json({ ok: true, sources: result.sources.map((record) => ({
        discovery_id: record.discovery_id, company: record.company, revision: record.revision,
        created_at: record.created_at, leads: record.leads,
        captures: record.captures.map((capture) => ({
          capture_id: capture.capture_id, source_url: capture.source_url,
          content_state: capture.content_state, captured_at: capture.captured_at,
        })),
      })) });
    }],
    ['/api/career-v0/company-dossiers', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_company_dossiers', { batch_id })) });
    }],
    ['/api/career-v0/company/search', 'POST', async (request) => {
      const { batch_id, job_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('search_company_sources', {
        batch_id: requireId(batch_id, 'batch_id'), job_id: requireId(job_id, 'job_id'),
      })) });
    }],
    ['/api/career-v0/company/prepare', 'POST', async (request) => {
      const { batch_id, job_id, discovery_id, capture_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('prepare_company_dossier', {
        batch_id: requireId(batch_id, 'batch_id'), job_id: requireId(job_id, 'job_id'),
        discovery_id: requireId(discovery_id, 'discovery_id'), capture_id: requireId(capture_id, 'capture_id'),
      })) });
    }],
    ['/api/career-v0/research', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_research', { batch_id })) });
    }],
    ['/api/career-v0/research/prepare', 'POST', async (request) => {
      const { batch_id, job_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('prepare_selected_research', {
        batch_id: requireId(batch_id, 'batch_id'), job_id: requireId(job_id, 'job_id'),
      })) });
    }],
    ['/api/career-v0/plans', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_plans', { batch_id })) });
    }],
    ['/api/career-v0/plans/prepare', 'POST', async (request) => {
      const { batch_id, job_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('prepare_tailoring_plan', {
        batch_id: requireId(batch_id, 'batch_id'), job_id: requireId(job_id, 'job_id'),
      })) });
    }],
    ['/api/career-v0/plan-exports', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_plan_exports', { batch_id })) });
    }],
    ['/api/career-v0/plan-previews', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_plan_previews', { batch_id })) });
    }],
    ['/api/career-v0/plan-decisions', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_plan_decisions', { batch_id })) });
    }],
    ['/api/career-v0/plans/workbook', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      const config = requiredConfiguration();
      const result = await bridge('export_plan_reviews', { batch_id });
      const target = artifactPath(config, result.artifact_path, 'plan_exports');
      return new Response(await readFile(target), {
        headers: {
          'content-type': XLSX_MIME,
          'content-disposition': `attachment; filename="${path.basename(target)}"`,
          'x-career-export-id': result.snapshot.export_id,
          'cache-control': 'no-store',
        },
      });
    }],
    ['/api/career-v0/plans/preview', 'POST', async (request) => {
      const export_id = requireId(new URL(request.url).searchParams.get('export_id'), 'export_id');
      if (request.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() !== XLSX_MIME) {
        throw Object.assign(new Error('expected XLSX upload'), { status: 415 });
      }
      const config = requiredConfiguration();
      const bytes = await boundedBody(request, MAX_XLSX);
      const folder = path.join(config.state, '_uploads');
      await mkdir(folder, { recursive: true });
      const uploadPath = path.join(folder, `upload-${randomUUID()}.xlsx`);
      await writeFile(uploadPath, bytes, { flag: 'wx' });
      try { return Response.json({ ok: true, ...(await bridge('preview_plan_reviews', { export_id, upload_path: uploadPath })) }); }
      finally { await unlink(uploadPath).catch(() => {}); }
    }],
    ['/api/career-v0/plans/confirm', 'POST', async (request) => {
      const { preview_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('confirm_plan_reviews', {
        preview_id: requireId(preview_id, 'preview_id'),
      })) });
    }],
    ['/api/career-v0/resume-artifacts', 'GET', async (request) => {
      const batch_id = requireId(new URL(request.url).searchParams.get('batch_id'), 'batch_id');
      return Response.json({ ok: true, ...(await bridge('list_resume_artifacts', { batch_id })) });
    }],
    ['/api/career-v0/resumes/generate', 'POST', async (request) => {
      const { plan_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('generate_resume_candidate', {
        plan_id: requireId(plan_id, 'plan_id'),
      })) });
    }],
    ['/api/career-v0/resumes/pdf', 'GET', async (request) => {
      const artifact_id = requireId(new URL(request.url).searchParams.get('artifact_id'), 'artifact_id');
      const result = await bridge('get_resume_artifact', { artifact_id });
      if (!result.artifact) return errorResponse('resume artifact not found', 404);
      const target = artifactPath(requiredConfiguration(), result.artifact.pdf_path, 'resumes');
      const bytes = await readFile(target);
      if (createHash('sha256').update(bytes).digest('hex') !== result.artifact.pdf_sha256) {
        return errorResponse('resume PDF hash differs from artifact record', 409);
      }
      return new Response(bytes, { headers: {
        'content-type': 'application/pdf',
        'content-disposition': `inline; filename="${path.basename(target)}"`,
        'cache-control': 'no-store',
      } });
    }],
    ['/api/career-v0/resumes/page-image', 'GET', async (request) => {
      const url = new URL(request.url);
      const artifact_id = requireId(url.searchParams.get('artifact_id'), 'artifact_id');
      const page = Number(url.searchParams.get('page'));
      if (!Number.isInteger(page) || page < 1) return errorResponse('page must be a positive integer', 400);
      const result = await bridge('get_resume_artifact', { artifact_id });
      if (!result.artifact) return errorResponse('resume artifact not found', 404);
      const images = result.artifact.qa?.page_image_paths || [];
      const hashes = result.artifact.qa?.page_image_sha256 || [];
      if (page > images.length || !hashes[page - 1]) return errorResponse('page image unavailable', 404);
      const target = artifactPath(requiredConfiguration(), images[page - 1], 'resumes');
      const bytes = await readFile(target);
      if (createHash('sha256').update(bytes).digest('hex') !== hashes[page - 1]) {
        return errorResponse('page image hash differs from artifact record', 409);
      }
      return new Response(bytes, { headers: {
        'content-type': 'image/png', 'cache-control': 'no-store',
      } });
    }],
    ['/api/career-v0/resumes/review', 'POST', async (request) => {
      const { artifact_id, decision, reviewed_pdf_sha256, visual_checks, owner_comment } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('review_resume_candidate', {
        artifact_id: requireId(artifact_id, 'artifact_id'), decision,
        reviewed_pdf_sha256, visual_checks, owner_comment,
      })) });
    }],
    ['/api/career-v0/handoff/export', 'POST', async (request) => {
      const { artifact_id } = await jsonBody(request);
      return Response.json({ ok: true, ...(await bridge('export_handoff', {
        artifact_id: requireId(artifact_id, 'artifact_id'),
      })) });
    }],
    ['/api/career-v0/handoffs', 'GET', async (request) => {
      const artifact_id = requireId(new URL(request.url).searchParams.get('artifact_id'), 'artifact_id');
      return Response.json({ ok: true, ...(await bridge('list_handoffs', { artifact_id })) });
    }],
    ['/api/career-v0/handoff/zip', 'GET', async (request) => {
      const handoff_id = requireId(new URL(request.url).searchParams.get('handoff_id'), 'handoff_id');
      const result = await bridge('get_handoff', { handoff_id });
      if (!result.handoff) return errorResponse('handoff not found', 404);
      const target = artifactPath(requiredConfiguration(), result.handoff.zip_path, 'handoffs');
      return new Response(await readFile(target), { headers: {
        'content-type': 'application/zip',
        'content-disposition': `attachment; filename="${path.basename(target)}"`,
        'cache-control': 'no-store',
      } });
    }],
  ];
  for (const [routePath, method, handler] of routes) {
    ctx.effect(() => ctx.connection.fetch.register({
      path: routePath,
      methods: [method],
      requestBody: method === 'GET' ? 'buffered' : 'streaming',
      async fetch(request) {
        try { return await handler(request); }
        catch (error) { return errorResponse(error?.message || 'Career Host error', error?.status || 500); }
      },
    }), `career-v0: ${method} ${routePath}`);
  }
}
