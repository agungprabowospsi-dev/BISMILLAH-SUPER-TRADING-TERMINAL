// frontend/src/components/knowledge_base/KnowledgeBasePage.jsx
import React, { useState, useEffect, useRef } from 'react'
import { Upload, BookOpen, CheckSquare, Square, ChevronDown, ChevronUp, Trash2, Search, RefreshCw, BookMarked, Zap } from 'lucide-react'
import clsx from 'clsx'

const API = 'https://bismillah-super-trading-terminal-production.up.railway.app'

const CATEGORY_COLORS = {
  Technical:    { bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200' },
  SMC:          { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  Bandarmology: { bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200' },
  Quant:        { bg: 'bg-teal-50',   text: 'text-teal-700',   border: 'border-teal-200' },
  Macro:        { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
  Sentiment:    { bg: 'bg-pink-50',   text: 'text-pink-700',   border: 'border-pink-200' },
  Fundamental:  { bg: 'bg-lime-50',   text: 'text-lime-700',   border: 'border-lime-200' },
  Decision:     { bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200' },
  Risk:         { bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200' },
  AI:           { bg: 'bg-cyan-50',   text: 'text-cyan-700',   border: 'border-cyan-200' },
  Alert:        { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' },
}

function ScoreBar({ score }) {
  const pct = Math.round(score * 100)
  const color = pct >= 80 ? '#16a34a' : pct >= 60 ? '#0ea5e9' : pct >= 40 ? '#f59e0b' : '#94a3b8'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="font-mono text-xs font-semibold" style={{ color }}>{pct}%</span>
    </div>
  )
}

function EngineRow({ score, onToggle, disabled }) {
  const cat = CATEGORY_COLORS[score.category] || CATEGORY_COLORS.Technical
  const [expanded, setExpanded] = useState(false)
  return (
    <div className={clsx(
      'border rounded-lg transition-all duration-200',
      score.is_approved ? 'border-accent-green/30 bg-green-50/30' : 'border-slate-200 bg-white'
    )}>
      <div className="flex items-center gap-3 px-3 py-2">
        {/* Checkbox */}
        <button onClick={() => !disabled && onToggle(score.engine_name, !score.is_approved)}
          disabled={disabled}
          className="shrink-0 transition-transform hover:scale-110">
          {score.is_approved
            ? <CheckSquare className="w-4 h-4 text-accent-green" />
            : <Square className="w-4 h-4 text-slate-400" />}
        </button>
        {/* Engine index */}
        <span className="font-mono text-xs text-slate-400 w-6 shrink-0">{score.engine_index}</span>
        {/* Engine name */}
        <span className="text-sm font-medium text-slate-700 flex-1 truncate">{score.engine_name}</span>
        {/* Category badge */}
        <span className={clsx('hidden sm:inline-flex text-[10px] font-semibold px-1.5 py-0.5 rounded border shrink-0', cat.bg, cat.text, cat.border)}>
          {score.category}
        </span>
        {/* Score bar */}
        <div className="shrink-0"><ScoreBar score={score.relevance_score} /></div>
        {/* User override indicator */}
        {score.user_override && (
          <span className="text-[9px] font-mono text-purple-500 bg-purple-50 border border-purple-200 px-1 rounded shrink-0">MANUAL</span>
        )}
        {/* Expand reasoning */}
        {score.claude_reasoning && (
          <button onClick={() => setExpanded(!expanded)} className="shrink-0 text-slate-400 hover:text-slate-600">
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        )}
      </div>
      {expanded && score.claude_reasoning && (
        <div className="px-10 pb-2 text-xs text-slate-500 italic border-t border-slate-100 pt-1.5">
          💬 {score.claude_reasoning}
        </div>
      )}
    </div>
  )
}

function DocumentCard({ doc, onSelect, onDelete, isSelected }) {
  const statusColor = {
    analyzed: 'text-accent-green bg-green-50 border-green-200',
    analyzing: 'text-amber-600 bg-amber-50 border-amber-200',
    error: 'text-red-600 bg-red-50 border-red-200',
    processing: 'text-blue-600 bg-blue-50 border-blue-200',
  }[doc.status] || 'text-slate-500 bg-slate-50 border-slate-200'

  return (
    <div onClick={() => onSelect(doc.id)}
      className={clsx(
        'border rounded-xl p-3 cursor-pointer transition-all duration-200 hover:shadow-md',
        isSelected ? 'border-accent-green bg-green-50/40 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'
      )}>
      <div className="flex items-start gap-2">
        <BookMarked className={clsx('w-4 h-4 mt-0.5 shrink-0', isSelected ? 'text-accent-green' : 'text-slate-400')} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-700 truncate">{doc.original_name}</div>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className={clsx('text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded border', statusColor)}>
              {doc.status.toUpperCase()}
            </span>
            <span className="text-[10px] text-slate-400 font-mono">{doc.page_count} hal</span>
            <span className="text-[10px] text-slate-400 font-mono">{doc.total_chunks} chunks</span>
            <span className="text-[10px] text-accent-green font-mono font-semibold">{doc.approved_engines}/34 engines</span>
          </div>
          {doc.description && (
            <div className="text-[10px] text-slate-400 mt-1 truncate">{doc.description}</div>
          )}
        </div>
        <button onClick={e => { e.stopPropagation(); onDelete(doc.id) }}
          className="shrink-0 p-1 rounded hover:bg-red-50 text-slate-300 hover:text-red-400 transition-colors">
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </div>
  )
}

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState([])
  const [selectedDocId, setSelectedDocId] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')
  const [uploadResult, setUploadResult] = useState(null)
  const [error, setError] = useState(null)
  const [description, setDescription] = useState('')
  const [threshold, setThreshold] = useState(60)
  const [filterGroup, setFilterGroup] = useState('all')
  const [stats, setStats] = useState(null)
  const [toggling, setToggling] = useState(null)
  const fileInputRef = useRef()

  useEffect(() => { loadDocuments(); loadStats() }, [])

  useEffect(() => {
    if (selectedDocId) loadDocumentDetail(selectedDocId)
  }, [selectedDocId])

  async function loadDocuments() {
    try {
      const r = await fetch(`${API}/api/kb/documents`)
      const d = await r.json()
      setDocuments(d.documents || [])
    } catch (e) { setError('Gagal load dokumen') }
  }

  async function loadStats() {
    try {
      const r = await fetch(`${API}/api/kb/stats`)
      const d = await r.json()
      setStats(d.stats)
    } catch {}
  }

  async function loadDocumentDetail(docId) {
    try {
      const r = await fetch(`${API}/api/kb/documents/${docId}`)
      const d = await r.json()
      if (d.success) setSelectedDoc(d)
    } catch (e) { setError('Gagal load detail dokumen') }
  }

  async function handleUpload(file) {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      setError('Hanya file PDF yang didukung'); return
    }
    setUploading(true); setError(null); setUploadResult(null)
    setUploadProgress('Mengirim file ke server...')
    try {
      const form = new FormData()
      form.append('file', file)
      if (description) form.append('description', description)
      const r = await fetch(`${API}/api/kb/upload`, { method: 'POST', body: form })
      const d = await r.json()
      if (!r.ok) { setError(d.detail || 'Upload gagal'); setUploading(false); return }
      const jobId = d.job_id
      if (!jobId) { setError('Tidak ada job_id dari server'); setUploading(false); return }
      const pollSteps = [
        'File diterima ✓ — ekstrak teks...',
        'Chunking konten PDF...',
        'Claude analisis engines 1-10...',
        'Claude analisis engines 11-20...',
        'Claude analisis engines 21-34...',
        'Menyimpan ke database...',
        'Hampir selesai...',
      ]
      let si = 0
      const iv = setInterval(() => {
        if (si < pollSteps.length) { setUploadProgress(pollSteps[si]); si++ }
      }, 5000)
      for (let attempt = 0; attempt < 120; attempt++) {
        await new Promise(res => setTimeout(res, 3000))
        try {
          const jr = await fetch(`${API}/api/kb/jobs/${jobId}`)
          const jd = await jr.json()
          if (jd.status === 'completed' || jd.status === 'done') {
            clearInterval(iv)
            const res = jd.result || jd
            setUploadResult({
              message: res.message || 'Upload berhasil!',
              document_id: res.document_id,
              total_pages: res.total_pages,
              total_chunks: res.total_chunks,
              approved_count: res.approved_count,
            })
            setUploadProgress('')
            setDescription('')
            await loadDocuments(); await loadStats()
            if (res.document_id) setSelectedDocId(res.document_id)
            setUploading(false); return
          }
          if (jd.status === 'failed') {
            clearInterval(iv)
            setError('Proses gagal: ' + (jd.error || 'Unknown'))
            setUploading(false); return
          }
          if (jd.progress) setUploadProgress(jd.progress)
        } catch {}
      }
      clearInterval(iv)
      setError('Timeout. Cek tab Buku Tersimpan!')
    } catch (e) {
      setError('Network error: ' + e.message)
    }
    setUploading(false)
  }

  async function handleToggleEngine(engineName, isApproved) {
    if (!selectedDocId || toggling) return
    setToggling(engineName)
    try {
      await fetch(`${API}/api/kb/documents/${selectedDocId}/engines/${engineName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_approved: isApproved })
      })
      await loadDocumentDetail(selectedDocId)
      await loadDocuments()
    } catch (e) { setError('Gagal update engine') }
    setToggling(null)
  }

  async function handleApplyThreshold() {
    if (!selectedDocId) return
    try {
      await fetch(`${API}/api/kb/documents/${selectedDocId}/apply-threshold`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ threshold: threshold / 100 })
      })
      await loadDocumentDetail(selectedDocId)
      await loadDocuments()
    } catch (e) { setError('Gagal apply threshold') }
  }

  async function handleDelete(docId) {
    if (!confirm('Hapus dokumen ini?')) return
    try {
      await fetch(`${API}/api/kb/documents/${docId}`, { method: 'DELETE' })
      if (selectedDocId === docId) { setSelectedDocId(null); setSelectedDoc(null) }
      await loadDocuments()
      await loadStats()
    } catch (e) { setError('Gagal hapus dokumen') }
  }

  const engineScores = selectedDoc?.engine_scores || []
  const filteredScores = filterGroup === 'all' ? engineScores
    : filterGroup === 'approved' ? engineScores.filter(e => e.is_approved)
    : engineScores.filter(e => {
        const groups = { '1': [1,10], '2': [11,15], '3': [16,28], '4': [29,34] }
        const [min, max] = groups[filterGroup] || [1,34]
        return e.engine_index >= min && e.engine_index <= max
      })

  const approvedCount = engineScores.filter(e => e.is_approved).length

  return (
    <div style={{ padding: '16px', maxWidth: 1200, margin: '0 auto' }}>

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-800 flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-accent-green" />
            Knowledge Base
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">Upload buku trading → Claude auto-analisis relevansi ke 34 engines</p>
        </div>
        {stats && (
          <div className="flex gap-3">
            {[
              { label: 'Buku', value: stats.total_documents || 0 },
              { label: 'Halaman', value: stats.total_pages || 0 },
              { label: 'Chunks', value: stats.total_chunks || 0 },
            ].map(s => (
              <div key={s.label} className="text-center px-3 py-1.5 bg-white border border-slate-200 rounded-lg">
                <div className="font-mono font-bold text-slate-800 text-base">{s.value}</div>
                <div className="text-[10px] text-slate-400">{s.label}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* LEFT: Upload + Document List */}
        <div className="lg:col-span-1 flex flex-col gap-3">

          {/* Upload Box */}
          <div className="bg-white border-2 border-dashed border-slate-300 rounded-xl p-4 hover:border-accent-green/50 transition-colors">
            <input ref={fileInputRef} type="file" accept=".pdf" className="hidden"
              onChange={e => e.target.files[0] && handleUpload(e.target.files[0])} />

            {uploading ? (
              <div className="text-center py-2">
                <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                <div className="text-xs font-mono text-slate-600 animate-pulse">{uploadProgress}</div>
                <div className="text-[10px] text-slate-400 mt-1">Ini mungkin 20-30 detik...</div>
              </div>
            ) : (
              <>
                <div className="text-center mb-3">
                  <Upload className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                  <div className="text-sm font-semibold text-slate-600">Upload Buku Trading</div>
                  <div className="text-xs text-slate-400">PDF · Max 50MB</div>
                </div>
                <input
                  type="text"
                  placeholder="Deskripsi buku (opsional)"
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 mb-2 focus:outline-none focus:border-accent-green"
                />
                <button onClick={() => fileInputRef.current?.click()}
                  className="w-full py-2 bg-accent-green text-white text-sm font-semibold rounded-lg hover:bg-green-600 transition-colors flex items-center justify-center gap-2">
                  <Upload className="w-4 h-4" /> Pilih PDF
                </button>
              </>
            )}
          </div>

          {/* Upload Result */}
          {uploadResult && !uploading && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-3">
              <div className="text-sm font-semibold text-green-700 mb-1">✅ Upload Berhasil!</div>
              <div className="text-xs text-green-600">{uploadResult.message}</div>
              <div className="grid grid-cols-3 gap-2 mt-2">
                {[
                  { label: 'Halaman', val: uploadResult.total_pages },
                  { label: 'Chunks', val: uploadResult.total_chunks },
                  { label: 'Auto-✓', val: `${uploadResult.approved_count}/34` },
                ].map(s => (
                  <div key={s.label} className="text-center bg-white rounded-lg p-1.5 border border-green-200">
                    <div className="font-mono font-bold text-green-700 text-sm">{s.val}</div>
                    <div className="text-[9px] text-green-500">{s.label}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-xs text-red-600">
              ⚠️ {error}
              <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">✕</button>
            </div>
          )}

          {/* Document List */}
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600">Buku Tersimpan ({documents.length})</span>
            <button onClick={() => { loadDocuments(); loadStats() }}
              className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600">
              <RefreshCw className="w-3 h-3" />
            </button>
          </div>

          <div className="flex flex-col gap-2 max-h-96 overflow-y-auto">
            {documents.length === 0 ? (
              <div className="text-center py-8 text-slate-400">
                <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <div className="text-xs">Belum ada buku. Upload PDF pertamamu!</div>
              </div>
            ) : (
              documents.map(doc => (
                <DocumentCard key={doc.id} doc={doc}
                  isSelected={selectedDocId === doc.id}
                  onSelect={setSelectedDocId}
                  onDelete={handleDelete} />
              ))
            )}
          </div>
        </div>

        {/* RIGHT: Engine Scores */}
        <div className="lg:col-span-2">
          {!selectedDoc ? (
            <div className="bg-white border border-slate-200 rounded-xl h-full flex items-center justify-center min-h-64">
              <div className="text-center text-slate-400">
                <Search className="w-10 h-10 mx-auto mb-3 opacity-20" />
                <div className="text-sm font-semibold">Pilih buku untuk lihat analisis</div>
                <div className="text-xs mt-1">Klik salah satu buku di kiri</div>
              </div>
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">

              {/* Doc header */}
              <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-slate-800 text-sm truncate max-w-xs">
                      {selectedDoc.document?.original_name}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {selectedDoc.document?.page_count} hal · {selectedDoc.document?.total_chunks} chunks
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-center px-3 py-1 bg-accent-green/10 border border-accent-green/30 rounded-lg">
                      <span className="font-mono font-bold text-accent-green text-base">{approvedCount}</span>
                      <span className="font-mono text-xs text-slate-400">/34</span>
                      <div className="text-[9px] text-slate-400">approved</div>
                    </div>
                  </div>
                </div>

                {/* Threshold control */}
                <div className="flex items-center gap-3 mt-3">
                  <span className="text-xs text-slate-500 shrink-0">Threshold:</span>
                  <input type="range" min="0" max="100" value={threshold}
                    onChange={e => setThreshold(Number(e.target.value))}
                    className="flex-1 h-1.5 accent-green-500" />
                  <span className="font-mono text-xs font-bold text-slate-700 w-8">{threshold}%</span>
                  <button onClick={handleApplyThreshold}
                    className="px-3 py-1 bg-accent-green text-white text-xs font-semibold rounded-lg hover:bg-green-600 transition-colors flex items-center gap-1">
                    <Zap className="w-3 h-3" /> Apply
                  </button>
                </div>
              </div>

              {/* Filter tabs */}
              <div className="flex gap-1 px-4 py-2 border-b border-slate-100 overflow-x-auto">
                {[
                  { id: 'all', label: `Semua (${engineScores.length})` },
                  { id: 'approved', label: `✓ Approved (${approvedCount})` },
                  { id: '1', label: 'G1 Technical' },
                  { id: '2', label: 'G2 Bandarmology' },
                  { id: '3', label: 'G3 Quant/Macro' },
                  { id: '4', label: 'G4 Decision' },
                ].map(f => (
                  <button key={f.id} onClick={() => setFilterGroup(f.id)}
                    className={clsx(
                      'text-[10px] font-semibold px-2 py-1 rounded-lg whitespace-nowrap transition-colors',
                      filterGroup === f.id
                        ? 'bg-accent-green text-white'
                        : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                    )}>
                    {f.label}
                  </button>
                ))}
              </div>

              {/* Engine list */}
              <div className="p-3 flex flex-col gap-1.5 max-h-[500px] overflow-y-auto">
                {filteredScores.length === 0 ? (
                  <div className="text-center py-8 text-xs text-slate-400">Tidak ada engine di filter ini</div>
                ) : (
                  filteredScores.map(score => (
                    <EngineRow key={score.engine_name} score={score}
                      onToggle={handleToggleEngine}
                      disabled={toggling === score.engine_name} />
                  ))
                )}
              </div>

              {/* Footer hint */}
              <div className="px-4 py-2 border-t border-slate-100 bg-slate-50/50">
                <p className="text-[10px] text-slate-400">
                  💡 Centang manual untuk override Claude. Engine yang di-approve akan mendapat konteks dari buku ini saat analisis saham.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
