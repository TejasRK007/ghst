import React, { useEffect, useMemo, useState } from 'react';
import { api, getApiBase, setApiBase, setApiErrorListener } from './services/api';

const TABS = [
  ['overview', 'Overview'],
  ['cases', 'Deletion requests'],
  ['datasets', 'CSV datasets'],
  ['evidence', 'Evidence files'],
  ['output', 'output.csv'],
];

function pretty(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  const text = String(value);
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}

function JsonBlock({ value }) {
  return <pre className="json-block">{pretty(value)}</pre>;
}

function DataTable({ columns = [], rows = [], onRowClick, rowKey = 'case_id' }) {
  if (!rows.length) return <div className="empty-state">No rows are present in this file or page.</div>;
  return (
    <div className="table-frame">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row[rowKey] || ''}-${index}`} onClick={onRowClick ? () => onRowClick(row) : undefined} className={onRowClick ? 'clickable-row' : ''}>
              {columns.map((column) => {
                const value = row[column];
                const text = value === undefined || value === null ? '' : String(value);
                return <td key={column} title={text}>
                  {text.length > 320 || column.endsWith('_json')
                    ? <details><summary>View value ({text.length} chars)</summary><JsonBlock value={value} /></details>
                    : text || '—'}
                </td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailSection({ title, value }) {
  const entries = Array.isArray(value) ? value : value ? [value] : [];
  return <section className="detail-section">
    <h3>{title}<span>{entries.length}</span></h3>
    {entries.length ? entries.map((entry, index) => <JsonBlock key={index} value={entry} />) : <div className="empty-state">No matching rows were found in the supplied files.</div>}
  </section>;
}

export default function Workspace() {
  const [tab, setTab] = useState('overview');
  const [apiUrl, setApiUrl] = useState(getApiBase());
  const [apiErrors, setApiErrors] = useState([]);
  const [health, setHealth] = useState(null);
  const [overview, setOverview] = useState(null);
  const [datasetFiles, setDatasetFiles] = useState([]);
  const [evidenceFiles, setEvidenceFiles] = useState([]);
  const [datasetPath, setDatasetPath] = useState('deletion_requests.csv');
  const [datasetView, setDatasetView] = useState(null);
  const [tableSearch, setTableSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selectedCase, setSelectedCase] = useState(null);
  const [selectedEvidence, setSelectedEvidence] = useState(null);
  const [caseData, setCaseData] = useState(null);
  const [investigation, setInvestigation] = useState(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setApiErrorListener((failure) => setApiErrors((current) => [failure, ...current.filter((item) => item.url !== failure.url)].slice(0, 4)));
    refreshAll();
  }, []);

  async function refreshAll() {
    const results = await Promise.allSettled([api.health(), api.overview(), api.datasets(), api.evidence()]);
    if (results[0].status === 'fulfilled') setHealth(results[0].value);
    if (results[1].status === 'fulfilled') setOverview(results[1].value);
    if (results[2].status === 'fulfilled') setDatasetFiles(results[2].value.files || []);
    if (results[3].status === 'fulfilled') setEvidenceFiles(results[3].value.files || []);
  }

  useEffect(() => {
    if (tab === 'datasets' || tab === 'cases') loadDataset(datasetPath, page, tableSearch);
    if (tab === 'output') loadOutput(page);
  }, [tab, datasetPath, page, tableSearch]);

  async function loadDataset(path, currentPage = 1, search = '') {
    try {
      const result = await api.dataset(path, { page: currentPage, page_size: 100, search });
      setDatasetView(result);
    } catch {
      setDatasetView(null);
    }
  }

  async function loadOutput(currentPage = 1) {
    try {
      const result = await api.output({ page: currentPage, page_size: 100 });
      setDatasetView(result);
    } catch {
      setDatasetView(null);
    }
  }

  async function openCase(row) {
    const id = row.case_id;
    if (!id) return;
    setSelectedCase(id);
    setCaseData(null);
    setInvestigation(null);
    setAnswer(null);
    setLoading(true);
    try { setCaseData(await api.case(id)); } catch { /* visible API error is recorded globally */ }
    finally { setLoading(false); }
  }

  async function openEvidence(fileId) {
    setSelectedEvidence(fileId);
    setLoading(true);
    try { setSelectedEvidence(await api.evidenceDetail(fileId)); }
    catch { setSelectedEvidence(null); }
    finally { setLoading(false); }
  }

  async function runInvestigation() {
    if (!selectedCase) return;
    setLoading(true);
    setInvestigation(null);
    try {
      const result = await api.investigate(selectedCase);
      setInvestigation(result);
      const note = result.api_status_note || '';
      if (/failed|unavailable|not configured|no live model/i.test(note)) {
        setApiErrors((current) => [{ url: 'Groq model API', path: '/api/ai-agent/investigate', message: note, time: new Date().toISOString() }, ...current].slice(0, 4));
      }
    } catch { /* visible API error is recorded globally */ }
    finally { setLoading(false); }
  }

  async function askQuestion(event) {
    event.preventDefault();
    if (!selectedCase || !question.trim()) return;
    setLoading(true);
    setAnswer(null);
    try { setAnswer(await api.ask(selectedCase, question.trim())); }
    catch { /* visible API error is recorded globally */ }
    finally { setLoading(false); }
  }

  async function generateCsv() {
    setGenerating(true);
    setApiErrors([]);
    try {
      await api.generateOutput();
      await refreshAll();
      await loadOutput(1);
    } catch {
      await refreshAll();
      await loadOutput(1);
    }
    finally { setGenerating(false); }
  }

  async function reconnect(event) {
    event.preventDefault();
    setApiErrors([]);
    setApiBase(apiUrl);
    setDatasetView(null);
    await refreshAll();
    if (tab === 'datasets' || tab === 'cases') await loadDataset(datasetPath, 1, tableSearch);
    if (tab === 'output') await loadOutput(1);
  }

  const summaryCards = useMemo(() => [
    ['Request cases', health?.request_count],
    ['CSV datasets', health?.dataset_csv_count],
    ['Evidence files', health?.evidence_file_count],
    ['Output rows', health?.output_rows],
  ], [health]);

  const activeFiles = datasetFiles;
  const requestsFile = activeFiles.find((file) => file.name === 'deletion_requests.csv');

  return <div className="app-shell">
    <header className="top-header">
      <div className="header-brand"><div className="eyebrow"><span aria-hidden="true">🦇</span> HALLOWEEN HACKATHON <span aria-hidden="true">☠️ 🎃</span></div><h1>Ghost Data Deletion Audit</h1><p>Inspect every supplied request, dataset, policy, activity record, evidence file, and output row.</p></div>
      <div className="halloween-sky" aria-hidden="true">
        <span className="halloween-moon" />
        <span className="halloween-bat halloween-bat-one">🦇</span>
        <span className="halloween-bat halloween-bat-two">🦇</span>
        <span className="halloween-ghost">👻</span>
        <img src="./ghost-pumpkin.svg" alt="" />
      </div>
      <div className={`connection-pill ${health ? 'connected' : 'disconnected'}`}><span />{health ? 'Dataset API connected' : 'Dataset API unavailable'}</div>
    </header>

    {apiErrors.length > 0 && <aside className="api-error" role="alert">
      <div className="api-error-title">An API request failed</div>
      <p>Share a replacement API URL or provider endpoint and I can connect it. No demo data is shown.</p>
      {apiErrors.map((failure, index) => <div className="api-error-item" key={`${failure.url}-${index}`}><code>{failure.url}</code><span>{failure.message}</span></div>)}
      <form className="api-config" onSubmit={reconnect}><label htmlFor="api-url">API base URL</label><input id="api-url" value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} placeholder="http://localhost:8000"/><button>Reconnect</button></form>
    </aside>}

    <section className="summary-grid">
      {summaryCards.map(([label, value]) => <div className="summary-card" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}
    </section>

    <nav className="tabs" aria-label="Dataset sections">
      {TABS.map(([id, label]) => <button key={id} onClick={() => { setTab(id); setPage(1); }} className={tab === id ? 'selected' : ''}>{label}</button>)}
    </nav>

    {tab === 'overview' && <main className="content-grid">
      <section className="panel wide"><div className="panel-heading"><div><h2>Supplied CSV files</h2><p>Rows and columns read directly from dataset/.</p></div></div>
        <div className="table-frame"><table><thead><tr><th>File</th><th>Rows</th><th>Columns</th><th>Size</th><th>Modified</th></tr></thead><tbody>{activeFiles.map((file) => <tr key={file.path} className="clickable-row" onClick={() => { setDatasetPath(file.path); setTableSearch(''); setPage(1); setTab(file.name === 'deletion_requests.csv' ? 'cases' : 'datasets'); }}><td>{file.path}</td><td>{file.rows}</td><td>{file.columns.join(', ')}</td><td>{file.size_bytes.toLocaleString()} bytes</td><td>{file.modified_at}</td></tr>)}</tbody></table></div>
      </section>
      <section className="panel"><h2>Evidence manifest</h2><p>{evidenceFiles.length} listed files from evidence_files.csv.</p><button className="button" onClick={() => setTab('evidence')}>Browse evidence</button></section>
      <section className="panel"><h2>Output validation</h2><p>{health?.output_valid ? 'Root output.csv passes its structural checks.' : 'Root output.csv needs attention or has not been generated.'}</p><button className="button" onClick={() => { setTab('output'); setPage(1); }}>Review output.csv</button></section>
      <section className="panel wide brief-card"><h2>Audit workflow</h2><p>Resolve current and historical identifiers, inspect supplied evidence at each audit cutoff, apply deletion_rules.csv, and produce ordered findings, remediation, and verification steps.</p><p>The case result panel shows the source records used for the selected request. Workflow status and activity results remain labeled as claims.</p></section>
    </main>}

    {(tab === 'cases' || tab === 'datasets') && <main className="panel data-panel">
      <div className="panel-heading"><div><h2>{tab === 'cases' ? 'Deletion requests' : 'CSV datasets'}</h2><p>{datasetView ? `${datasetView.total_rows} rows in ${datasetView.path}` : 'Loading dataset rows…'}</p></div>
        <div className="table-controls"><select aria-label="Choose a dataset" value={datasetPath} onChange={(event) => { setDatasetPath(event.target.value); setPage(1); }}>{activeFiles.map((file) => <option key={file.path} value={file.path}>{file.path} · {file.rows} rows</option>)}</select><input value={tableSearch} onChange={(event) => { setTableSearch(event.target.value); setPage(1); }} placeholder="Search every column" aria-label="Search dataset"/></div>
      </div>
      {datasetView && <DataTable columns={datasetView.columns} rows={datasetView.rows} onRowClick={tab === 'cases' && datasetPath === 'deletion_requests.csv' ? openCase : undefined} />}
      <div className="pagination"><span>Page {datasetView?.page || page} of {datasetView?.total_pages || '—'} · {datasetView?.total_rows ?? '—'} matching rows</span><div><button disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button><button disabled={page >= (datasetView?.total_pages || 1)} onClick={() => setPage((current) => current + 1)}>Next</button></div></div>
      {tab === 'cases' && datasetPath !== 'deletion_requests.csv' && <div className="hint">Select deletion_requests.csv to open full case details.</div>}
      {tab === 'cases' && datasetPath === 'deletion_requests.csv' && <div className="hint">Select a row to inspect identity history, matching activity, evidence, audit result, and output for that case.</div>}
    </main>}

    {tab === 'evidence' && <main className="content-grid evidence-layout">
      <section className="panel"><div className="panel-heading"><div><h2>Evidence files</h2><p>Manifest entries and captured times from evidence_files.csv.</p></div><input value={tableSearch} onChange={(event) => setTableSearch(event.target.value)} placeholder="Filter manifest"/></div>
        <div className="evidence-list">{evidenceFiles.filter((file) => !tableSearch || `${file.file_id} ${file.file_path} ${file.origin}`.toLowerCase().includes(tableSearch.toLowerCase())).map((file) => <button key={file.file_id} className={`evidence-row ${selectedEvidence?.file_id === file.file_id ? 'active' : ''}`} onClick={() => openEvidence(file.file_id)}><strong>{file.file_id}</strong><span>{file.file_path}</span><small>{file.captured_at} · {file.available ? `${file.size_bytes.toLocaleString()} bytes` : 'MISSING'}</small></button>)}</div>
      </section>
      <section className="panel evidence-viewer"><h2>{selectedEvidence?.file_id || 'Select an evidence file'}</h2>{selectedEvidence?.file_path && <><p>{selectedEvidence.file_path} · {selectedEvidence.origin} · captured {selectedEvidence.captured_at}</p><div className="evidence-actions"><a className="button" href={api.evidenceFileUrl(selectedEvidence.file_id)} target="_blank" rel="noreferrer">Open original file</a>{selectedEvidence.file_type === 'pdf' && <a className="button secondary" href={api.evidenceFileUrl(selectedEvidence.file_id)} target="_blank" rel="noreferrer">Open PDF</a>}</div><JsonBlock value={selectedEvidence.content}/></>}</section>
    </main>}

    {tab === 'output' && <main className="panel data-panel">
      <div className="panel-heading"><div><h2>Root output.csv</h2><p>{datasetView?.total_rows ?? '—'} rows · {datasetView?.modified_at || 'not generated'}</p></div><div className="actions"><button className="button" disabled={generating} onClick={generateCsv}>{generating ? 'Generating…' : 'Generate output.csv'}</button><a className="button secondary" href={api.downloadUrl()} download="output.csv">Download CSV</a></div></div>
      {datasetView?.validation && <div className={`validation-box ${datasetView.validation.valid ? 'valid' : 'invalid'}`}><strong>{datasetView.validation.valid ? 'Output structure valid' : 'Output needs correction'}</strong>{!datasetView.validation.valid && <ul>{datasetView.validation.errors.slice(0, 20).map((error, index) => <li key={index}>{error}</li>)}</ul>}</div>}
      {datasetView && <DataTable columns={datasetView.columns} rows={datasetView.rows} />}
      <div className="pagination"><span>Page {datasetView?.page || page} of {datasetView?.total_pages || '—'}</span><div><button disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button><button disabled={page >= (datasetView?.total_pages || 1)} onClick={() => setPage((current) => current + 1)}>Next</button></div></div>
    </main>}

    {selectedCase && <div className="overlay" onClick={() => setSelectedCase(null)}><aside className="drawer" onClick={(event) => event.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow">CASE DETAIL</span><h2>{selectedCase}</h2></div><button className="close-button" onClick={() => setSelectedCase(null)}>Close</button></div>{loading && !caseData ? <p>Loading case records…</p> : !caseData ? <div className="api-error" role="alert">The case API failed. Close this panel to view the failed endpoint and connect a replacement API.</div> : <>
      <DetailSection title="Request row" value={caseData.request}/>
      <DetailSection title="Resolved identity" value={caseData.identity}/>
      <DetailSection title="Identity change history" value={caseData.identity_history}/>
      <DetailSection title="Related system activity (at/before audit_at)" value={caseData.activity}/>
      <DetailSection title="Matched evidence observations" value={caseData.evidence_matches}/>
      <DetailSection title="Current output row" value={caseData.output}/>
      <section className="detail-section"><h3>AI evidence investigation</h3><button className="button" disabled={loading} onClick={runInvestigation}>{loading ? 'Investigating…' : 'Run investigation'}</button>{investigation && <><p>{investigation.agent_mode} · {investigation.model}</p><DetailSection title="Investigation report" value={investigation.report}/><DetailSection title="Tool evidence" value={investigation.tool_data}/></>}</section>
      <form className="ask-form" onSubmit={askQuestion}><label htmlFor="case-question">Ask about this case</label><textarea id="case-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question grounded in this case's evidence"/><button className="button" disabled={loading || !question.trim()}>{loading ? 'Working…' : 'Ask'}</button>{answer && <DetailSection title="Answer and cited evidence" value={answer}/>}</form>
    </>}</aside></div>}

    <footer><span>Data source: local dataset/ and root output.csv</span><span>{health?.status || 'API status unavailable'}</span></footer>
  </div>;
}
