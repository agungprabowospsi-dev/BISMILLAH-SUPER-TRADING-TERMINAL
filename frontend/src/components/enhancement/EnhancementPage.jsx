import React, { useState, useRef, useEffect } from 'react'
import { Send, Terminal, Bot, User, Play, CheckCircle, XCircle, Loader, Trash2 } from 'lucide-react'

const BACKEND = import.meta.env.VITE_BACKEND_URL || 'https://backend-production-daed.up.railway.app'

const QUICK_COMMANDS = [
  { label: '🏥 Health Check', prompt: 'Cek kesehatan semua sistem terminal' },
  { label: '📋 Git Log', prompt: 'Tampilkan 5 commit terakhir' },
  { label: '🔍 Audit Kode', prompt: 'Audit semua file Python di backend, cari kode yang tidak efisien' },
  { label: '📊 Status Engines', prompt: 'Cek apakah semua 34 engines berjalan dengan baik' },
  { label: '🐛 Debug', prompt: 'Cek apakah ada error di log backend terbaru' },
  { label: '📁 Struktur', prompt: 'Tampilkan struktur folder project saat ini' },
]

function CommandBlock({ command, result, onRun, running }) {
  return (
    <div style={{ margin:'8px 0', border:'1px solid #e2e8f0', borderRadius:8, overflow:'hidden' }}>
      <div style={{ background:'#f1f5f9', padding:'6px 12px', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <code style={{ fontFamily:'monospace', fontSize:12, color:'#475569' }}>$ {command}</code>
        {!result && (
          <button onClick={() => onRun(command)} disabled={running}
            style={{ display:'flex', alignItems:'center', gap:4, padding:'3px 10px', background:'#0ea5e9', border:'none', borderRadius:4, color:'white', cursor:'pointer', fontSize:11, fontFamily:'monospace' }}>
            {running ? <Loader size={10} style={{ animation:'spin 1s linear infinite' }}/> : <Play size={10}/>}
            {running ? 'Running...' : 'Run'}
          </button>
        )}
        {result && (
          <span style={{ display:'flex', alignItems:'center', gap:4, fontSize:11, fontFamily:'monospace', color: result.returncode === 0 ? '#22c55e' : '#ef4444' }}>
            {result.returncode === 0 ? <CheckCircle size={12}/> : <XCircle size={12}/>}
            {result.status}
          </span>
        )}
      </div>
      {result && (
        <pre style={{ margin:0, padding:'8px 12px', background:'#0f172a', color:'#e2e8f0', fontFamily:'monospace', fontSize:11, overflowX:'auto', maxHeight:300, overflowY:'auto', whiteSpace:'pre-wrap', wordBreak:'break-all' }}>
          {result.stdout || result.stderr || '(no output)'}
        </pre>
      )}
    </div>
  )
}

function Message({ msg, onRunCommand, runningCmd }) {
  const isUser = msg.role === 'user'

  // Parse content — pisahkan teks biasa dan command blocks
  const renderContent = (content) => {
    const parts = content.split(/(<cmd>.*?<\/cmd>)/gs)
    return parts.map((part, i) => {
      const cmdMatch = part.match(/<cmd>(.*?)<\/cmd>/s)
      if (cmdMatch) {
        const cmd = cmdMatch[1].trim()
        const result = msg.results?.[cmd]
        return <CommandBlock key={i} command={cmd} result={result} onRun={onRunCommand} running={runningCmd === cmd}/>
      }
      // Render teks biasa
      return part ? (
        <p key={i} style={{ fontFamily:'monospace', fontSize:13, lineHeight:1.7, color: isUser ? 'white' : '#1e293b', margin:'4px 0', whiteSpace:'pre-wrap' }}>
          {part}
        </p>
      ) : null
    })
  }

  return (
    <div style={{ display:'flex', gap:10, marginBottom:16, flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <div style={{
        width:32, height:32, borderRadius:8, flexShrink:0,
        background: isUser ? '#0ea5e9' : '#1e293b',
        border: isUser ? 'none' : '1px solid #334155',
        display:'flex', alignItems:'center', justifyContent:'center'
      }}>
        {isUser ? <User size={16} color="white"/> : <Bot size={16} color="#0ea5e9"/>}
      </div>
      <div style={{
        maxWidth:'85%',
        background: isUser ? '#0ea5e9' : '#ffffff',
        border: isUser ? 'none' : '1px solid #e2e8f0',
        borderRadius: isUser ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
        padding:'10px 14px',
        boxShadow:'0 1px 3px rgba(0,0,0,0.08)',
        width: isUser ? 'auto' : '100%'
      }}>
        {renderContent(msg.content)}
        {msg.timestamp && (
          <p style={{ fontFamily:'monospace', fontSize:9, color: isUser ? 'rgba(255,255,255,0.6)' : '#94a3b8', margin:'6px 0 0', textAlign:'right' }}>
            {msg.timestamp}
          </p>
        )}
      </div>
    </div>
  )
}

export default function EnhancementPage() {
  const [messages, setMessages] = useState([{
    role: 'assistant',
    content: 'Bismillah! Saya siap membantu pengembangan dan perbaikan BISMILLAH SUPER TRADING TERMINAL.\n\nKetik perintah apa saja — saya akan analisis, buat command, dan jalankan langsung di server. 🚀',
    timestamp: new Date().toLocaleTimeString('id-ID')
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [runningCmd, setRunningCmd] = useState(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior:'smooth' })
  }, [messages, loading])

  const runCommand = async (command, msgIndex) => {
    setRunningCmd(command)
    try {
      const res = await fetch(`${BACKEND}/api/enhancement/exec`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ command })
      })
      const result = await res.json()

      setMessages(prev => prev.map((msg, i) => {
        if (i === msgIndex) {
          return { ...msg, results: { ...(msg.results||{}), [command]: result } }
        }
        return msg
      }))

      // Auto-kirim output ke Claude untuk analisis
      if (result.stdout || result.stderr) {
        await sendMessage(`Output dari command \`${command}\`:\n\`\`\`\n${result.stdout || result.stderr}\n\`\`\`\nApa kesimpulannya?`, true)
      }
    } catch(e) {
      console.error(e)
    } finally {
      setRunningCmd(null)
    }
  }

  const sendMessage = async (text, isAuto = false) => {
    const userMsg = text || input.trim()
    if (!userMsg || loading) return
    if (!isAuto) setInput('')

    const timestamp = new Date().toLocaleTimeString('id-ID')
    
    setMessages(prev => {
      const newMessages = isAuto ? prev : [...prev, { role:'user', content:userMsg, timestamp }]
      return newMessages
    })

    if (!isAuto) {
      setMessages(prev => [...prev, { role:'user', content:userMsg, timestamp }])
    }

    setLoading(true)

    try {
      // Build history untuk API
      const history = messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }))

      if (!isAuto) {
        history.push({ role:'user', content:userMsg })
      } else {
        history.push({ role:'user', content:userMsg })
      }

      const res = await fetch(`${BACKEND}/api/enhancement/chat`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ messages: history })
      })
      const data = await res.json()

      const assistantMsg = {
        role:'assistant',
        content: data.content || 'Error: tidak ada response',
        commands: data.commands || [],
        results: {},
        timestamp: new Date().toLocaleTimeString('id-ID')
      }

      setMessages(prev => [...prev, assistantMsg])

      // Auto-run commands kalau ada
      if (data.commands && data.commands.length > 0) {
        const msgIdx = messages.length + (isAuto ? 0 : 1)
        for (const cmd of data.commands) {
          await runCommand(cmd, msgIdx)
        }
      }

    } catch(e) {
      setMessages(prev => [...prev, {
        role:'assistant',
        content:'Error koneksi ke backend. Cek apakah Railway online.',
        timestamp: new Date().toLocaleTimeString('id-ID')
      }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearChat = () => {
    setMessages([{
      role:'assistant',
      content:'Chat dibersihkan. Siap menerima perintah baru! 🚀',
      timestamp: new Date().toLocaleTimeString('id-ID')
    }])
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'calc(100vh - 120px)', maxWidth:1000, margin:'0 auto', padding:'0 20px' }}>
      {/* Header */}
      <div style={{ padding:'16px 0 12px', borderBottom:'1px solid #e2e8f0', marginBottom:12 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <div style={{ width:36, height:36, borderRadius:8, background:'#7c3aed', display:'flex', alignItems:'center', justifyContent:'center' }}>
            <Terminal size={20} color="white"/>
          </div>
          <div>
            <h1 style={{ fontFamily:'monospace', fontSize:16, fontWeight:'bold', color:'#1e293b', margin:0 }}>
              ⚡ Enhancement Terminal
            </h1>
            <p style={{ fontFamily:'monospace', fontSize:10, color:'#64748b', margin:0 }}>
              Claude AI + Railway Server · Bisa edit, debug, deploy langsung
            </p>
          </div>
          <button onClick={clearChat} style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:4, padding:'6px 10px', background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:6, cursor:'pointer', fontFamily:'monospace', fontSize:11, color:'#64748b' }}>
            <Trash2 size={12}/> Clear
          </button>
        </div>
      </div>

      {/* Quick Commands */}
      <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:12 }}>
        {QUICK_COMMANDS.map((cmd, i) => (
          <button key={i} onClick={() => sendMessage(cmd.prompt)}
            style={{ padding:'5px 10px', background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:20, fontFamily:'monospace', fontSize:10, color:'#475569', cursor:'pointer', whiteSpace:'nowrap' }}>
            {cmd.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div style={{ flex:1, overflowY:'auto', paddingRight:4 }}>
        {messages.map((msg, i) => (
          <Message key={i} msg={msg}
            onRunCommand={(cmd) => runCommand(cmd, i)}
            runningCmd={runningCmd}
          />
        ))}
        {loading && (
          <div style={{ display:'flex', gap:10, marginBottom:16 }}>
            <div style={{ width:32, height:32, borderRadius:8, background:'#1e293b', border:'1px solid #334155', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
              <Bot size={16} color="#7c3aed"/>
            </div>
            <div style={{ background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:'4px 16px 16px 16px', padding:'12px 16px', boxShadow:'0 1px 3px rgba(0,0,0,0.08)' }}>
              <div style={{ display:'flex', gap:4, alignItems:'center' }}>
                {[0,1,2].map(i => (
                  <div key={i} style={{ width:8, height:8, borderRadius:'50%', background:'#7c3aed', animation:`bounce 1.2s ease-in-out ${i*0.2}s infinite` }}/>
                ))}
                <span style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', marginLeft:6 }}>Menganalisis...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef}/>
      </div>

      {/* Input */}
      <div style={{ padding:'12px 0', borderTop:'1px solid #e2e8f0' }}>
        <div style={{ display:'flex', gap:8, alignItems:'flex-end' }}>
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey} placeholder="Ketik perintah... contoh: 'Tambah fitur X', 'Fix bug Y', 'Cek status Z'" rows={2}
            style={{ flex:1, padding:'10px 14px', border:'1px solid #e2e8f0', borderRadius:12, fontFamily:'monospace', fontSize:13, color:'#1e293b', resize:'none', outline:'none', background:'#f8fafc', lineHeight:1.5 }}
          />
          <button onClick={() => sendMessage()} disabled={loading || !input.trim()}
            style={{ width:44, height:44, borderRadius:12, border:'none', background: loading || !input.trim() ? '#e2e8f0' : '#7c3aed', color:'white', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
            {loading ? <Loader size={18} style={{ animation:'spin 1s linear infinite' }}/> : <Send size={18}/>}
          </button>
        </div>
        <p style={{ fontFamily:'monospace', fontSize:9, color:'#94a3b8', margin:'6px 0 0' }}>
          Enter kirim · Shift+Enter baris baru · Command dijalankan langsung di Railway server
        </p>
      </div>

      <style>{`
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-8px)} }
        @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
      `}</style>
    </div>
  )
}
