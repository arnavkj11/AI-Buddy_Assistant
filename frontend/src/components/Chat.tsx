import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchAuthSession, signOut } from 'aws-amplify/auth';
import { MessageSquare, Plus, LogOut, Send, Book, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { awsConfig } from '../aws-config.ts';

interface Session { session_id: string; title: string; last_active_at: string; }
interface Source { doc_title: string; page_or_section: string; }
interface Message { ts?: string; role: 'user' | 'assistant'; content: string; sources?: Source[] }

const API_ENPOINT = awsConfig.API.REST.AiBuddyApi.endpoint;

export default function Chat() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputStr, setInputStr] = useState('');
  const [loading, setLoading] = useState(false);
  const [docStatus, setDocStatus] = useState<any>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    checkAuthAndLoad();
    fetchDocStatus();
  }, []);

  useEffect(() => {
    if (activeSession) loadMessages(activeSession);
  }, [activeSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const getHeaders = async () => {
    try {
      const { tokens } = await fetchAuthSession();
      if (!tokens) throw new Error("No token");
      return { Authorization: `Bearer ${tokens.idToken?.toString()}`, 'Content-Type': 'application/json' };
    } catch (e) {
      navigate('/login');
      throw e;
    }
  };

  const checkAuthAndLoad = async () => {
    try {
      const headers = await getHeaders();
      const res = await fetch(`${API_ENPOINT}/v1/chats`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
        if (data.length > 0) setActiveSession(data[0].session_id);
      }
    } catch {}
  };

  const fetchDocStatus = async () => {
    try {
      const headers = await getHeaders();
      const res = await fetch(`${API_ENPOINT}/v1/docs/status`, { headers });
      if (res.ok) setDocStatus(await res.json());
    } catch {}
  };

  const loadMessages = async (sessionId: string) => {
    try {
      const headers = await getHeaders();
      const res = await fetch(`${API_ENPOINT}/v1/chats/${sessionId}/messages`, { headers });
      if (res.ok) setMessages(await res.json());
    } catch {}
  };

  const handleNewChat = async () => {
    try {
      const headers = await getHeaders();
      const res = await fetch(`${API_ENPOINT}/v1/chats`, { method: 'POST', headers });
      if (res.ok) {
        const data = await res.json();
        checkAuthAndLoad(); // reload list
        setActiveSession(data.session_id);
        setMessages([]);
      }
    } catch(e) { console.error(e) }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputStr.trim() || !activeSession || loading) return;
    const currentInput = inputStr;
    setInputStr('');
    setMessages(prev => [...prev, { role: 'user', content: currentInput }]);
    setLoading(true);

    try {
      const headers = await getHeaders();
      const res = await fetch(`${API_ENPOINT}/v1/chats/${activeSession}/messages`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message: currentInput })
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(prev => [...prev, { role: 'assistant', content: data.answer, sources: data.sources }]);
        checkAuthAndLoad(); // refresh titles and last active
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Error getting response.' }]);
      }
    } catch(err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await signOut();
    navigate('/login');
  };

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={handleNewChat}><Plus size={16}/> New Chat</button>
        </div>
        <div className="session-list">
          {sessions.map(s => (
            <div 
              key={s.session_id} 
              className={`session-item ${activeSession === s.session_id ? 'active' : ''}`}
              onClick={() => setActiveSession(s.session_id)}
            >
              <MessageSquare size={14} style={{marginRight:'0.5rem', display:'inline-block', verticalAlign:'middle'}} />
              {s.title}
            </div>
          ))}
        </div>
        <div className="sidebar-footer">
          <span style={{fontSize:'0.8rem', color:'var(--text-muted)'}}>AI Buddy Prototype</span>
          <button className="logout-btn" onClick={handleLogout} title="Logout"><LogOut size={18}/></button>
        </div>
      </div>

      {/* Main Area */}
      <div className="chat-main">
        <div className="chat-header">
          <div style={{fontWeight:600}}>Assistant</div>
          {docStatus && (
            <div className={`status-badge ${docStatus.processing > 0 ? 'processing' : ''}`}>
              <Book size={12} style={{marginRight:'4px', display:'inline'}}/>
              {docStatus.ready} Docs Ready • {docStatus.processing} Processing
            </div>
          )}
        </div>
        
        <div className="chat-history">
          {messages.length === 0 && (
            <div style={{margin:'auto', color:'var(--text-muted)', textAlign:'center'}}>
              <h2 style={{color:'var(--text-main)', marginBottom:'1rem'}}>How can I help you today?</h2>
              <p>Ask anything about onboarding, company policies, or standard procedures.</p>
            </div>
          )}
          {messages.map((m, idx) => (
            <div key={idx} className={`message message-${m.role}`}>
              <div className="message-bubble">
                {m.role === 'assistant' ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}
              </div>
              {m.sources && m.sources.length > 0 && (
                <div className="sources-panel">
                  <h4>Sources:</h4>
                  {m.sources.map((src, i) => (
                    <div key={i} className="source-item">
                       <FileText size={12} /> {src.doc_title} - {src.page_or_section}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && <div className="message message-assistant"><div className="message-bubble" style={{fontStyle:'italic', opacity:0.7}}>Thinking...</div></div>}
          <div ref={bottomRef} />
        </div>

        <div className="chat-input-area">
          <form className="chat-input-form" onSubmit={handleSend}>
            <input 
              value={inputStr} 
              onChange={(e) => setInputStr(e.target.value)} 
              placeholder="Message AI Buddy..." 
              disabled={loading}
              autoFocus
            />
            <button type="submit" disabled={!inputStr.trim() || loading || !activeSession}>
              <Send size={18} />
            </button>
          </form>
          <p style={{textAlign:'center', fontSize:'0.75rem', color:'var(--text-muted)', marginTop:'0.75rem'}}>AI can make mistakes. Check important info.</p>
        </div>
      </div>
    </div>
  );
}
