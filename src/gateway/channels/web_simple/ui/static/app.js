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

  /** Full markdown-to-HTML renderer: headings, lists, code, tables, blockquotes, etc. */
  function renderMarkdown(text) {
    // Escape HTML first
    let html = esc(text);

    // Code blocks (```...```) — escape before any other processing
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      var cls = lang ? ' class="language-' + lang + '"' : '';
      return '<pre><code' + cls + '>' + code.trim() + '</code></pre>';
    });

    // Horizontal rules (---, ***, ___) on its own line
    html = html.replace(/^(?:[-*_]\s*){3,}$/gm, '<hr>');

    // Headings (# through ######)
    html = html.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
    html = html.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

    // Blockquotes (> text)
    html = html.replace(/^&gt;\s+(.+)$/gm, '<blockquote>$1</blockquote>');

    // Unordered lists (- item, * item)
    html = html.replace(/^(?:[-*])\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // Ordered lists (1. item)
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    // Re-wrap any <li> groups not already in <ul> into <ol>
    // (Simple approach: convert remaining bare <li> sequences to <ol>)
    html = html.replace(/(?:<\/li>\n?)?(<li>.*<\/li>\n?)+(?!<\/[uo]l>)/g, '<ol>$&</ol>');

    // Inline code (`...`) — after code blocks so already-wrapped is untouched
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold (**...**)
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic (*...*) — careful not to match inside HTML tags
    html = html.replace(/(^|[> \n])\*([^*]+)\*/g, '$1<em>$2</em>');

    // URLs → clickable links
    html = html.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );

    // Inline images ![alt](url)
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" loading="lazy">');

    // Wrap consecutive non-tag text in paragraphs (text between blank lines)
    var lines = html.split('\n');
    var inParagraph = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      // Skip empty lines, block elements, standalone HR, headings, lists, etc.
      if (
        !line ||
        line.startsWith('<h') ||
        line.startsWith('<pre') ||
        line.startsWith('<ul') ||
        line.startsWith('<ol') ||
        line.startsWith('<li') ||
        line.startsWith('<blockquote') ||
        line.startsWith('<hr') ||
        line.startsWith('</') ||
        line.endsWith('</pre>') ||
        line.endsWith('</h6>') ||
        line.endsWith('</h1>') ||
        line.endsWith('</ul>') ||
        line.endsWith('</ol>') ||
        line.endsWith('</blockquote>')
      ) {
        if (inParagraph) {
          lines[i - 1] = lines[i - 1] + '</p>';
          inParagraph = false;
        }
        continue;
      }
      if (!inParagraph) {
        lines[i] = '<p>' + line;
        inParagraph = true;
      }
    }
    if (inParagraph) {
      lines[lines.length - 1] = lines[lines.length - 1] + '</p>';
    }
    html = lines.join('\n');

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

  // ----- Command definitions -----

  var COMMANDS = [
    { prefix: '/agents', description: 'List all available agents', hasArgs: false },
    { prefix: '/agent', description: '/agent <id> — chat with a specific agent', hasArgs: true },
    { prefix: '/workflows', description: 'List all available workflows', hasArgs: false },
    { prefix: '/workflow', description: '/workflow <id> — run a workflow', hasArgs: true },
    { prefix: '/councils', description: 'List all available councils', hasArgs: false },
    { prefix: '/council', description: '/council <id> on "question" — deliberate', hasArgs: true },
    { prefix: '/clear', description: 'Clear the screen', hasArgs: false },
    { prefix: '/reset', description: 'Reset conversation context', hasArgs: false },
  ];

  var currentAgentId = null;
  var suggestionsEl = document.getElementById('suggestions');
  var filteredCommands = [];
  var suggestionIndex = -1;

  function isCommand(text) {
    return text.startsWith('/');
  }

  function showSuggestions(cmds) {
    filteredCommands = cmds;
    suggestionIndex = -1;
    if (!cmds || cmds.length === 0) {
      suggestionsEl.classList.add('hidden');
      suggestionsEl.innerHTML = '';
      return;
    }
    suggestionsEl.innerHTML = cmds
      .map(function (c, i) { return '<div class="suggestion-item" data-index="' + i + '">' + esc(c.prefix) + ' <span class="suggestion-desc">' + esc(c.description) + '</span></div>'; })
      .join('');
    suggestionsEl.classList.remove('hidden');
  }

  function selectSuggestion(index) {
    var items = suggestionsEl.querySelectorAll('.suggestion-item');
    items.forEach(function (el, i) {
      el.classList.toggle('selected', i === index);
    });
    suggestionIndex = index;
  }

  function applySuggestion(index) {
    var cmd = filteredCommands[index];
    if (!cmd) return;
    inputEl.value = cmd.prefix + ' ';
    inputEl.focus();
    suggestionsEl.classList.add('hidden');
  }

  // ----- Command execution -----

  async function executeCommand(cmd, args) {
    switch (cmd.prefix) {
      case '/agents':
        return executeListAgents();
      case '/agent':
        return executeAgentChat(args);
      case '/workflows':
        return executeListWorkflows();
      case '/workflow':
        return executeWorkflow(args);
      case '/councils':
        return executeListCouncils();
      case '/council':
        return executeCouncil(args);
      case '/clear':
        return executeClear();
      case '/reset':
        return executeReset();
    }
  }

  async function executeListAgents() {
    setLoading(true);
    setStatus('thinking');
    try {
      var res = await fetch('/agents');
      var data = await res.json();
      var text = '**Available Agents:**\n\n' + (Array.isArray(data) ? data : data.agents || []).map(function (a) {
        return '- **' + esc(a.agent_id || a.name || a) + '**' + (a.description ? ': ' + esc(a.description) : '');
      }).join('\n');
      addMessage('assistant', text);
    } catch (err) {
      addMessage('assistant', '⚠️ Error listing agents: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  async function executeAgentChat(args) {
    var id = args.trim();
    if (!id) {
      addMessage('assistant', '⚠️ Usage: `/agent <agent-id>` — e.g., `/agent devsquad-interviewer`');
      return;
    }
    currentAgentId = id;
    addMessage('assistant', '✅ Now chatting with agent **' + esc(id) + '**. All non-command messages will be sent to this agent.\n\nType `/agent` with no id to return to the default chat.');
  }

  async function executeListWorkflows() {
    setLoading(true);
    setStatus('thinking');
    try {
      var res = await fetch('/workflows');
      var data = await res.json();
      var items = Array.isArray(data) ? data : data.workflows || [];
      var text = '**Available Workflows:**\n\n' + (items.length === 0 ? '*None found*' : items.map(function (w) {
        return '- **' + esc(w.workflow_id || w.name || w) + '**' + (w.description ? ': ' + esc(w.description) : '');
      }).join('\n'));
      addMessage('assistant', text);
    } catch (err) {
      addMessage('assistant', '⚠️ Error listing workflows: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  async function executeWorkflow(args) {
    var id = args.trim();
    if (!id) {
      addMessage('assistant', '⚠️ Usage: `/workflow <workflow-id>` — e.g., `/workflow some-workflow`');
      return;
    }
    setLoading(true);
    setStatus('thinking');
    try {
      var res = await fetch('/workflows/' + encodeURIComponent(id) + '/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      var data = await res.json();
      addMessage('assistant', data.output || data.result || JSON.stringify(data, null, 2));
    } catch (err) {
      addMessage('assistant', '⚠️ Error running workflow: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  async function executeListCouncils() {
    setLoading(true);
    setStatus('thinking');
    try {
      var res = await fetch('/councils');
      var data = await res.json();
      var items = Array.isArray(data) ? data : data.councils || [];
      var text = '**Available Councils:**\n\n' + (items.length === 0 ? '*None found*' : items.map(function (c) {
        return '- **' + esc(c.council_id || c.name || c) + '**' + (c.description ? ': ' + esc(c.description) : '') + (c.members ? ' *(members: ' + esc(c.members.join(', ')) + ')*' : '');
      }).join('\n'));
      addMessage('assistant', text);
    } catch (err) {
      addMessage('assistant', '⚠️ Error listing councils: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  async function executeCouncil(args) {
    // Parse: /council <id> on "question"
    var match = args.match(/^(\S+)\s+on\s+"([\s\S]+)"$/);
    if (!match) {
      addMessage('assistant', '⚠️ Usage: `/council <council-id> on "your question"`\n\nExample: `/council general-nominal on "Should we use SQLite?"`');
      return;
    }
    var id = match[1].trim();
    var question = match[2].trim();

    setLoading(true);
    setStatus('thinking');
    try {
      var res = await fetch('/councils/' + encodeURIComponent(id) + '/deliberate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ problem: question }),
      });
      var data = await res.json();
      if (data.output) {
        addMessage('assistant', data.output, data.metadata);
      } else if (data.decision) {
        var text = '**Council Deliberation: ' + esc(data.council_id) + '**\n\n' +
          '**Decision:** ' + esc(data.decision) + '\n\n' +
          '**Confidence:** ' + Math.round((data.confidence || 0) * 100) + '%\n';
        if (data.member_analyses && data.member_analyses.length > 0) {
          text += '\n**Member Analyses:**\n\n';
          data.member_analyses.forEach(function (m) {
            text += '- **' + esc(m.member_id || m.member || '?') + '**: ' + esc(m.analysis || m.response || '') + '\n';
          });
        }
        addMessage('assistant', text, data.metadata);
      } else {
        addMessage('assistant', JSON.stringify(data, null, 2));
      }
    } catch (err) {
      addMessage('assistant', '⚠️ Council error: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  function executeClear() {
    messagesEl.innerHTML = '';
    // Restore empty state if element exists
    if (emptyState) {
      messagesEl.appendChild(emptyState);
    }
    saveMessages();
  }

  async function executeReset() {
    setLoading(true);
    setStatus('thinking');
    currentAgentId = null;
    try {
      await fetch('/reset', { method: 'POST' });
      // Clear local messages
      messagesEl.innerHTML = '';
      if (emptyState) {
        messagesEl.appendChild(emptyState);
      }
      localStorage.removeItem('chatHistory');
      addMessage('assistant', '✅ Context reset. Starting fresh.');
    } catch (err) {
      addMessage('assistant', '⚠️ Reset error: ' + esc(err.message));
    }
    setLoading(false);
    setStatus('connected');
  }

  // ----- Networking -----

  async function sendMessage(input) {
    setLoading(true);
    setStatus('thinking');

    // Route to specific agent if one is selected
    var url = '/run';
    var body = { input: input, metadata: {} };
    if (currentAgentId) {
      url = '/agents/' + encodeURIComponent(currentAgentId) + '/chat';
      body.agent_id = currentAgentId;
    }

    try {
      var res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        var err = await res.json().catch(function () { return {}; });
        throw new Error(err.detail || 'Request failed (' + res.status + ')');
      }

      var data = await res.json();
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

    var poll = async function () {
      try {
        var res = await fetch('/jobs/' + encodeURIComponent(id));
        if (!res.ok) {
          // 404 = not ready yet, keep polling
          if (res.status === 404) {
            scheduleNext();
            return;
          }
          throw new Error('Poll failed (' + res.status + ')');
        }

        var data = await res.json();

        // Check if we have output
        if (data.output || data.result) {
          var output = data.output || (data.result && data.result.output) || JSON.stringify(data);
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
    var titles = {
      connected: 'Connected',
      thinking: 'VAI is thinking…',
      error: 'Connection error',
    };
    statusEl.title = titles[state] || '';
  }

  // ----- Event handlers -----

  function handleSend() {
    var text = inputEl.value.trim();
    if (!text || sendBtn.disabled) return;

    addMessage('user', text);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    suggestionsEl.classList.add('hidden');
    saveMessages();

    if (isCommand(text)) {
      var spaceIdx = text.indexOf(' ');
      var prefix = spaceIdx === -1 ? text.toLowerCase() : text.substring(0, spaceIdx).toLowerCase();
      var args = spaceIdx === -1 ? '' : text.substring(spaceIdx + 1);
      var cmd = COMMANDS.find(function (c) { return c.prefix === prefix; });
      if (cmd) {
        executeCommand(cmd, args);
      } else {
        addMessage('assistant', '⚠️ Unknown command: ' + esc(prefix) + '\n\nType `/` to see available commands.');
      }
    } else {
      sendMessage(text);
    }
  }

  function handleKeydown(e) {
    // Autocomplete navigation (when suggestions visible)
    if (!suggestionsEl.classList.contains('hidden') && filteredCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        var next = Math.min(suggestionIndex + 1, filteredCommands.length - 1);
        selectSuggestion(next);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        var prev = suggestionIndex <= 0 ? 0 : suggestionIndex - 1;
        selectSuggestion(prev);
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && suggestionIndex >= 0)) {
        e.preventDefault();
        applySuggestion(suggestionIndex >= 0 ? suggestionIndex : 0);
        return;
      }
      if (e.key === 'Escape') {
        suggestionsEl.classList.add('hidden');
        return;
      }
    }

    // Normal send on Enter
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput() {
    // Auto-resize textarea
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';

    // Autocomplete filter
    var val = inputEl.value;
    if (val.startsWith('/')) {
      var partial = val.toLowerCase();
      // Only show suggestions at the start of input, before any space
      if (val.indexOf(' ') === -1) {
        var matches = COMMANDS.filter(function (c) {
          return c.prefix.indexOf(partial) === 0;
        });
        showSuggestions(matches);
      } else {
        suggestionsEl.classList.add('hidden');
      }
    } else {
      suggestionsEl.classList.add('hidden');
    }
  }

  function saveMessages() {
    var msgs = [];
    messagesEl.querySelectorAll('.message').forEach(function (el) {
      var bubble = el.querySelector('.bubble');
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
    var history = loadHistory();
    if (history.length > 0) {
      if (emptyState && emptyState.parentNode) {
        emptyState.remove();
      }
      history.forEach(function (msg) { return addMessage(msg.role, msg.text); });
    }

    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').catch(function () {
        // SW registration failed — app still works online
      });
    }

    // Event listeners
    sendBtn.addEventListener('click', handleSend);
    inputEl.addEventListener('keydown', handleKeydown);
    inputEl.addEventListener('input', handleInput);
    inputEl.addEventListener('blur', function () {
      // Brief delay so suggestion clicks can register
      setTimeout(function () { suggestionsEl.classList.add('hidden'); }, 200);
    });

    // Click suggestion items via delegation
    suggestionsEl.addEventListener('click', function (e) {
      var item = e.target.closest('.suggestion-item');
      if (item) {
        var index = parseInt(item.dataset.index, 10);
        applySuggestion(index);
      }
    });

    // Keyboard-aware viewport on mobile
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', function () {
        var viewport = window.visualViewport;
        var inputBar = document.getElementById('input-bar');
        var keyboardHeight = window.innerHeight - viewport.height;
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
