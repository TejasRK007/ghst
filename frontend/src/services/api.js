const envBase = import.meta.env.VITE_API_BASE || '';
const initialBase = envBase || (window.location.port === '5173' ? 'http://localhost:8001' : window.location.origin);
const savedBase = localStorage.getItem('ghost-data-api-base');
// Migrate the old default from the previous setup while preserving custom API URLs.
if (window.location.port === '5173' && savedBase === 'http://localhost:8000' && !envBase) {
  localStorage.setItem('ghost-data-api-base', initialBase);
}
let apiBase = (!envBase && window.location.port === '5173' && savedBase === 'http://localhost:8000')
  ? initialBase
  : (savedBase || initialBase);
let errorListener = null;

export function setApiErrorListener(listener) {
  errorListener = listener;
}

export function getApiBase() {
  return apiBase;
}

export function setApiBase(value) {
  apiBase = String(value || '').trim().replace(/\/$/, '');
  localStorage.setItem('ghost-data-api-base', apiBase);
}

async function request(path, options = {}) {
  const url = `${apiBase}${path}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
    });
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === 'object' ? payload?.detail : payload;
      const message = typeof detail === 'string'
        ? detail
        : [detail?.message, detail?.run_output].filter(Boolean).join('\n') || JSON.stringify(detail || payload);
      throw new Error(`HTTP ${response.status}: ${message}`);
    }
    return payload;
  } catch (error) {
    const failure = { url, path, message: error.message || 'Network request failed', time: new Date().toISOString() };
    errorListener?.(failure);
    throw Object.assign(new Error(failure.message), { failure });
  }
}

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  });
  return search.toString();
}

export const api = {
  health: () => request('/api/health'),
  overview: () => request('/api/overview'),
  datasets: () => request('/api/datasets'),
  dataset: (path, params = {}) => request(`/api/datasets/table/${path.split('/').map(encodeURIComponent).join('/')}${query(params) ? `?${query(params)}` : ''}`),
  case: (caseId) => request(`/api/cases/${encodeURIComponent(caseId)}`),
  evidence: () => request('/api/evidence'),
  evidenceDetail: (fileId) => request(`/api/evidence/${encodeURIComponent(fileId)}`),
  output: (params = {}) => request(`/api/output${query(params) ? `?${query(params)}` : ''}`),
  generateOutput: () => request('/api/output/generate', { method: 'POST' }),
  investigate: (caseId) => request('/api/ai-agent/investigate', { method: 'POST', body: JSON.stringify({ case_id: caseId }) }),
  ask: (caseId, question) => request('/api/ai-agent/chat', { method: 'POST', body: JSON.stringify({ case_id: caseId, question }) }),
  downloadUrl: () => `${apiBase}/api/download/output.csv`,
  evidenceFileUrl: (fileId) => `${apiBase}/api/evidence/${encodeURIComponent(fileId)}/file`,
};
