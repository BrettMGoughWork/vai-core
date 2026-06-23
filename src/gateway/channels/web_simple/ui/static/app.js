// VAI Web Client — vanilla JS PWA frontend
// Communicates with the gateway via POST /run and GET /jobs/{job_id}.
// Persists chat history in localStorage. No framework required.
(function () {
  'use strict';

  // ----- DOM references -----
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('user-input');
  const sendBtn = document.getElementById('send-btn');
  const loadingEl = document.getElementById('loading');
  const statusEl = document.getElementById('status');
  const emptyState = messagesEl.querySelector('.empty-state');

  // ----- State -----
  let jobId = null;
  let pollTimer = null;
  let pollDelay = 500; // ms, exponential backoff
  const POLL_MAX = 5000;

  // ----- Chat history persistence -----
  const HISTORY_KEY = 'vai_chat_history';

  function loadHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function saveHistory(messages) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(messages));
    } catch {
      // localStorage full or unavailable — silently ignore
    }
  }

  function clearHistory() {
    localStorage.removeItem(HISTORY_KEY);
    messagesEl.innerHTML = '';
    const es = document.createElement('div');
    es.className = 'empty-state';
    es.innerHTML = '<div class="empty-icon">🤖</div><p>Ask VAI anything. Start a conversation below.</p>';
    messagesEl.appendChild(es);
  }

  // Expose clearHistory globally so it can be called from console or future settings UI
  window.clearVaiHistory = clearHistory;

  // ----- Render helpers -----

  /** Escape HTML to prevent XSS */
  function esc(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  /** Very simple markdown-ish rendering: code blocks, inline code, bold, links */
  function renderMarkdown(text) {
    let html = esc(text);
    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold (**...**)
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italic (*...*)
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // URLs → clickable links
    html = html.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );
    return html;
  }

  function addMessage(role, text, metadata) {
    // Remove empty state
    if (emptyState && emptyState.parentNode) {
      emptyState.remove();
    }

    const msg = document.createElement('div');
    msg.className = 'message ' + role;

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = renderMarkdown(text);

    msg.appendChild(bubble);

    if (metadata && metadata.correlation_id) {
      const meta = document.createElement('div');
      meta.className = 'message-meta';
      meta.textContent = 'id: ' + metadata.correlation_id.slice(0, 8);
      msg.appendChild(meta);
    }

    messagesEl.appendChild(msg);
    scrollToBottom();
  }

  function scrollToBottom() {
    const chat = document.getElementById('chat');
    requestAnimationFrame(() => {
      chat.scrollTop = chat.scrollHeight;
    });
  }

  // ----- Networking -----

  async function sendMessage(input) {
    setLoading(true);
    setStatus('thinking');

    // Build payload
    const payload = { input: input };
    const metadata = {};
    payload.metadata = metadata;

    try {
      const res = await fetch('/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Request failed (' + res.status + ')');
      }

      const data = await res.json();
      // Extract job_id from response
      jobId = data.job_id || data.correlation_id || data.id;
      pollDelay = 500;

      if (data.output) {
        // Synchronous response
        addMessage('assistant', data.output, data.metadata);
        setLoading(false);
        setStatus('connected');
        return;
      }

      // Asynchronous — start polling
      if (jobId) {
        pollForResult(jobId);
      } else {
        // No job_id and no output — show what we got
        addMessage('assistant', JSON.stringify(data), data.metadata);
        setLoading(false);
        setStatus('connected');
      }
    } catch (err) {
      addMessage('assistant', '⚠️ Error: ' + esc(err.message));
      setLoading(false);
      setStatus('error');
    }
  }

  function pollForResult(id) {
    if (pollTimer) clearTimeout(pollTimer);

    const poll = async () => {
      try {
        const res = await fetch('/jobs/' + encodeURIComponent(id));
        if (!res.ok) {
          // 404 = not ready yet, keep polling
          if (res.status === 404) {
            scheduleNext();
            return;
          }
          throw new Error('Poll failed (' + res.status + ')');
        }

        const data = await res.json();

        // Check if we have output
        if (data.output || data.result) {
          const output = data.output || (data.result && data.result.output) || JSON.stringify(data);
          addMessage('assistant', output, data.metadata || data);
          setLoading(false);
          setStatus('connected');
          jobId = null;
          return;
        }

        // Still processing — poll again with backoff
        scheduleNext();
      } catch (err) {
        addMessage('assistant', '⚠️ Polling error: ' + esc(err.message));
        setLoading(false);
        setStatus('error');
      }
    };

    function scheduleNext() {
      pollTimer = setTimeout(poll, pollDelay);
      pollDelay = Math.min(pollDelay * 1.5, POLL_MAX);
    }

    scheduleNext();
  }

  // ----- UI state -----

  function setLoading(on) {
    loadingEl.classList.toggle('hidden', !on);
    sendBtn.disabled = on;
    inputEl.disabled = on;
  }

  function setStatus(state) {
    statusEl.className = 'status-dot ' + state;
    const titles = {
      connected: 'Connected',
      thinking: 'VAI is thinking…',
      error: 'Connection error',
    };
    statusEl.title = titles[state] || '';
  }

  // ----- Event handlers -----

  function handleSend() {
    const text = inputEl.value.trim();
    if (!text || sendBtn.disabled) return;

    addMessage('user', text);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    saveMessages();

    sendMessage(text);
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput() {
    // Auto-resize textarea
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';
  }

  function saveMessages() {
    const msgs = [];
    messagesEl.querySelectorAll('.message').forEach((el) => {
      const bubble = el.querySelector('.bubble');
      if (bubble) {
        msgs.push({
          role: el.classList.contains('user') ? 'user' : 'assistant',
          text: bubble.textContent,
        });
      }
    });
    saveHistory(msgs);
  }

  // ----- Init -----

  function init() {
    // Restore history
    const history = loadHistory();
    if (history.length > 0) {
      if (emptyState && emptyState.parentNode) {
        emptyState.remove();
      }
      history.forEach((msg) => addMessage(msg.role, msg.text));
    }

    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').catch(() => {
        // SW registration failed — app still works online
      });
    }

    // Event listeners
    sendBtn.addEventListener('click', handleSend);
    inputEl.addEventListener('keydown', handleKeydown);
    inputEl.addEventListener('input', handleInput);

    // Keyboard-aware viewport on mobile
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', () => {
        const viewport = window.visualViewport;
        const inputBar = document.getElementById('input-bar');
        const keyboardHeight = window.innerHeight - viewport.height;
        if (keyboardHeight > 100) {
          inputBar.style.paddingBottom = (keyboardHeight - 60) + 'px';
        } else {
          inputBar.style.paddingBottom = '';
        }
      });
    }

    // Focus input on load
    inputEl.focus();
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
