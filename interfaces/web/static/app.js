'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
const number = value => value == null ? '—' : Number(value).toLocaleString('ru-RU');
let ready = false;
let choosingFolder = false;
let latest = null;
let catalogue = [];
let activeTab = 'log';
let logSignature = '';
let lastDocumentsRun = null;
let localError = '';
const phases = {
  idle: ['Готово к запуску', 'Выберите источники, укажите закон и папку для сохранения.'],
  starting: ['Запускаем…', 'Подготавливаем новую сессию браузера.'],
  login: ['Выполняется…', 'Входим в источник. В режиме отладки можно пройти дополнительные подтверждения.'],
  home: ['Выполняется…', 'Вход выполнен. Подготавливаем поиск.'],
  'search-start': ['Выполняется…', 'Заполняем поисковый запрос.'],
  'query-filled': ['Выполняется…', 'Отправляем запрос в источник.'],
  'find-clicked': ['Выполняется…', 'Ожидаем результаты поиска.'],
  results: ['Выполняется…', 'Открываем найденный закон.'],
  'first-card-opened': ['Выполняется…', 'Открываем связи документа.'],
  'court-practice-high-courts': ['Выполняется…', 'Собираем ссылки на судебные акты.'],
  export: ['Выполняется…', 'Сохраняем документы и дополняем общую таблицу.'],
  stopping: ['Останавливаем…', 'Дождитесь завершения текущего действия и выхода из системы.'],
  'logging-out': ['Завершаем…', 'Выполняем выход из источника.'],
  'logged-out': ['Завершаем…', 'Выход подтверждён. Закрываем браузер.'],
  'logout-unconfirmed': ['Завершаем…', 'Выход не подтверждён. Проверьте сессию вручную.'],
  'ner-unavailable': ['Подготовка…', 'Извлечение данных пока недоступно. Сохраним документы без дополнительных полей.'],
  done: ['Выгрузка завершена', 'Документы и общая таблица доступны в выбранной папке.'],
  stopped: ['Выгрузка остановлена', 'Сохранённые документы останутся на месте. Запуск можно повторить в ту же папку.'],
  failed: ['Выгрузка прервана', 'Сохранённый прогресс не потерян. Подробности — в журнале и сообщении ниже.']
};

async function api(path, data) {
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'X-App-Token': token, 'Content-Type': 'application/json'},
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Ошибка приложения.');
  return body;
}
function showError(message) {
  $('error').textContent = message || '';
  $('error').hidden = !message;
}
function reportError(message) { localError = message; showError(message); }
function empty(container, message) {
  container.replaceChildren();
  const p = document.createElement('p');
  p.className = 'empty-state'; p.textContent = message;
  container.append(p);
}
function selectedSources() {
  return [...document.querySelectorAll('input[name="source"]:checked')].map(input => input.value);
}
function updateSources() {
  const selected = selectedSources();
  document.querySelectorAll('.source-card').forEach(card => card.classList.toggle('selected', card.querySelector('input').checked));
  const credentialSource = catalogue.find(source => selected.includes(source.id) && source.requires_credentials);
  $('credentials').hidden = !credentialSource;
  $('account-notice').hidden = !credentialSource;
  $('login').required = !!credentialSource;
  $('password').required = !!credentialSource;
  $('login').disabled = !credentialSource || !!latest?.running;
  $('password').disabled = !credentialSource || !!latest?.running;
  $('login-label').textContent = credentialSource ? `Логин ${credentialSource.name}` : 'Логин источника';
  if (!latest?.run_id) $('run-subtitle').textContent = selected.length ? catalogue.filter(s => selected.includes(s.id)).map(s => s.name).join(' · ') : 'Выберите хотя бы один источник';
}
function updateNer() {
  $('ner-options').disabled = !$('ner-enabled').checked || !!latest?.running;
  $('api-key').disabled = true;
  $('ner-note').textContent = $('ner-enabled').checked
    ? 'Извлечение пока не реализовано. Настройки передадим в конфиг, документы сохраним без дополнительных полей.'
    : 'Блок в разработке. Сейчас сохраняются тексты документов и основная таблица.';
}
function updateTimer() {
  if (!latest?.started_at) { $('elapsed').textContent = 'Ещё не запускалась'; return; }
  const end = latest.finished_at ? Date.parse(latest.finished_at) : Date.now();
  const minutes = Math.max(0, Math.floor((end - Date.parse(latest.started_at)) / 60000));
  const duration = minutes < 1 ? 'меньше минуты' : minutes < 60 ? `${minutes} мин` : `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
  $('elapsed').textContent = `${latest.running ? 'Работает' : 'Время'} ${duration}`;
}
function renderLogs(state) {
  const logs = state.logs || [];
  const signature = JSON.stringify([state.run_id, logs, state.error]);
  if (signature === logSignature) return;
  logSignature = signature;
  const render = (container, rows, fallback) => {
    const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 45;
    container.replaceChildren();
    if (!rows.length) { empty(container, fallback); return; }
    for (const entry of rows) {
      const row = document.createElement('div');
      row.className = `log-row ${String(entry.level).toLowerCase()}`;
      const time = document.createElement('span'); time.className = 'log-time'; time.textContent = entry.time;
      const mark = document.createElement('span'); mark.className = 'log-mark'; mark.textContent = ['ERROR', 'WARNING'].includes(entry.level) ? '!' : '›';
      const message = document.createElement('span'); message.className = 'log-message';
      message.textContent = entry.message.replace(/^\d{2}:\d{2}:\d{2}\s+(DEBUG|INFO|WARNING|ERROR)\s+[\w.]+:\s*/, '');
      const status = message.textContent.match(/^Этап: (.+)$/);
      if (status) {
        const saved = status[1].match(/^saved:(\d+)$/);
        const skipped = status[1].match(/^skipped:(\d+)$/);
        if (saved) message.textContent = `Сохранено документов: ${saved[1]}`;
        else if (skipped) message.textContent = `Пропущено документов: ${skipped[1]}`;
        else if (phases[status[1]]) message.textContent = phases[status[1]][1];
      }
      row.append(time, mark, message); container.append(row);
    }
    if (follow) container.scrollTop = container.scrollHeight;
  };
  render($('journal-log'), logs, 'Здесь появится история работы. Пока можно настроить первую выгрузку.');
  const errors = logs.filter(entry => ['WARNING', 'ERROR'].includes(entry.level));
  if (state.error) errors.push({time: '', level: 'ERROR', message: state.error});
  render($('journal-errors'), errors, 'Сообщений об ошибках пока нет.');
}
function render(state) {
  latest = state;
  const key = /^(saved|skipped):/.test(state.phase) ? 'export' : state.phase;
  const [title, description] = phases[key] || ['Выполняется…', 'Ожидаем завершения текущего действия.'];
  $('phase').textContent = title; $('description').textContent = description;
  $('saved').textContent = $('saved-summary').textContent = number(state.saved);
  $('skipped').textContent = number(state.skipped);
  $('found').textContent = number(state.found);
  $('failed-count').textContent = number(state.failed || 0);
  $('errors-tab-count').textContent = `(${state.failed || 0})`;
  const completed = (state.saved || 0) + (state.skipped || 0);
  $('queued').textContent = state.found == null ? '—' : number(Math.max(0, state.found - completed));
  if (state.found > 0) {
    const percent = Math.min(100, Math.floor(completed / state.found * 100));
    $('progress').value = percent; $('progress-label').textContent = `${percent}%`;
  } else if (state.running) {
    $('progress').removeAttribute('value'); $('progress-label').textContent = 'Поиск документов';
  } else {
    $('progress').value = state.phase === 'done' ? 100 : 0;
    $('progress-label').textContent = state.phase === 'idle' ? 'Ожидание' : state.phase === 'done' ? 'Готово' : 'Остановлено';
  }
  $('directory').textContent = state.directory;
  $('save-directory').value = state.save_directory;
  $('save-directory').title = state.save_directory;
  $('settings').disabled = state.running;
  $('start').disabled = !ready || state.running || choosingFolder;
  $('choose-folder').disabled = state.running || choosingFolder;
  $('stop').hidden = !state.running;
  $('stop').disabled = ['stopping', 'logging-out'].includes(state.phase);
  $('status-dot').className = `status-dot ${state.running ? 'running' : state.phase}`;
  $('run-title').textContent = state.run_id ? `Выгрузка #${String(state.run_id).padStart(3, '0')}` : 'Новая выгрузка';
  if (state.started_at) {
    const time = new Date(state.started_at).toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
    $('run-subtitle').textContent = `Запущена в ${time} · ${(state.sources || []).join(' · ')}`;
  }
  $('logout').textContent = state.logout === true ? 'Выход из источника подтверждён.' : state.logout === false ? 'Выход не подтверждён. Проверьте сессию вручную.' : state.running ? 'Остановленную выгрузку можно продолжить в ту же папку.' : '';
  $('transport-summary').textContent = state.phase === 'done' ? ` · Из браузера: ${state.browser_texts || 0}` : '';
  $('run-warnings').replaceChildren();
  for (const warning of state.warnings || []) {
    const p = document.createElement('p'); p.textContent = warning; $('run-warnings').append(p);
  }
  showError(state.error || localError); updateTimer(); updateSources(); updateNer(); renderLogs(state);
  if (activeTab === 'documents' && state.phase === 'done' && lastDocumentsRun !== state.run_id) loadDocuments();
}
async function loadDocuments() {
  try {
    const result = await api('/api/documents');
    lastDocumentsRun = latest?.phase === 'done' ? latest.run_id : null;
    const container = $('journal-documents'); container.replaceChildren();
    if (!result.documents.length) { empty(container, 'Сохранённые акты появятся здесь после начала выгрузки.'); return; }
    const caption = document.createElement('p'); caption.className = 'muted'; caption.textContent = 'Сохранённые акты из общей таблицы (до 200 записей).'; container.append(caption);
    for (const item of result.documents) {
      const row = document.createElement('div'); row.className = 'document-row';
      const link = document.createElement('a'); link.textContent = item.title || 'Судебный акт';
      try { const url = new URL(item.url); if (['http:', 'https:'].includes(url.protocol)) { link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; } } catch { /* Display invalid URLs as plain text. */ }
      const source = document.createElement('small'); source.textContent = item.source || '';
      row.append(link, source); container.append(row);
    }
    lastDocumentsRun = latest?.phase === 'done' ? latest.run_id : null;
  } catch (error) { empty($('journal-documents'), error.message); }
}
function selectTab(name) {
  activeTab = name;
  for (const key of ['log', 'errors', 'documents']) {
    $(`tab-${key}`).classList.toggle('selected', key === name);
    $(`tab-${key}`).setAttribute('aria-selected', String(key === name));
    $(`journal-${key}`).hidden = key !== name;
  }
  if (name === 'documents') loadDocuments();
}
$('parser-form').addEventListener('submit', async event => {
  event.preventDefault(); $('start').disabled = true;
  try {
    localError = '';
    const state = await api('/api/start', {
      sources: selectedSources(), login: $('login').value, password: $('password').value,
      law: $('law').value, debug: $('debug').checked, overwrite: $('overwrite').checked,
      transport: 'browser',
      ner: {enabled: $('ner-enabled').checked, method: document.querySelector('input[name="ner-method"]:checked').value,
            fields: [...document.querySelectorAll('input[name="ner-field"]:checked')].map(input => input.value)}
    });
    $('password').value = ''; render(state);
  } catch (error) { reportError(error.message); $('start').disabled = !ready || !!latest?.running; }
});
$('show-password').addEventListener('click', () => {
  const visible = $('password').type === 'password'; $('password').type = visible ? 'text' : 'password';
  $('show-password').setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
  $('show-password').setAttribute('aria-pressed', String(visible));
});
$('ner-enabled').addEventListener('change', updateNer);
$('parser-form').addEventListener('input', () => { localError = ''; if (!latest?.error) showError(''); });
$('choose-folder').addEventListener('click', async () => {
  choosingFolder = true; $('choose-folder').disabled = true; $('start').disabled = true;
  try { render(await api('/api/choose-folder', {})); } catch (error) { reportError(error.message); }
  finally { choosingFolder = false; await refresh(); }
});
$('stop').addEventListener('click', async () => { try { render(await api('/api/stop', {})); } catch (error) { reportError(error.message); } });
$('open-folder').addEventListener('click', async () => { try { await api('/api/open-folder', {}); } catch (error) { reportError(error.message); } });
for (const tab of ['log', 'errors', 'documents']) $(`tab-${tab}`).addEventListener('click', () => selectTab(tab));
function help() { $('help-dialog').showModal(); }
$('nav-help').addEventListener('click', help); $('action-help').addEventListener('click', help);
$('nav-export').addEventListener('click', () => { window.scrollTo({top:0, behavior:'smooth'}); });
$('nav-settings').addEventListener('click', () => { $('advanced-panel').scrollIntoView({behavior:'smooth', block:'center'}); $('advanced-panel').focus({preventScroll:true}); });
for (const button of document.querySelectorAll('.dialog-close')) button.addEventListener('click', () => button.closest('dialog').close());
$('nav-runs').addEventListener('click', async () => {
  $('runs-dialog').showModal();
  try {
    const result = await api('/api/runs');
    const runs = [...result.runs];
    if (latest?.running) runs.push(latest);
    const list = $('runs-list'); list.replaceChildren();
    if (!runs.length) { empty(list, 'В этом сеансе ещё не было запусков.'); return; }
    for (const run of runs.reverse()) {
      const row = document.createElement('p'); row.className = 'run-list-item';
      const time = run.started_at ? new Date(run.started_at).toLocaleString('ru-RU') : '';
      row.textContent = `#${String(run.run_id).padStart(3, '0')} · ${time} · ${(run.sources || []).join(', ')} — сохранено ${run.saved}, пропущено ${run.skipped}.`;
      list.append(row);
    }
  } catch (error) { empty($('runs-list'), error.message); }
});
$('copy-log').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText((latest?.logs || []).map(entry => `${entry.time} ${entry.message}`).join('\n')); $('copy-log').textContent = 'Лог скопирован'; setTimeout(() => { $('copy-log').textContent = 'Скопировать лог'; }, 2000); }
  catch { reportError('Не удалось скопировать лог. Его можно выделить в журнале.'); }
});
async function initialize() {
  try {
    const options = await api('/api/options'); catalogue = options.sources;
    $('source-cards').replaceChildren();
    for (const source of catalogue) {
      const label = document.createElement('label'); label.className = 'source-card';
      const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'source'; input.value = source.id; input.checked = source.id === options.default_source; input.setAttribute('aria-label', source.name); input.addEventListener('change', updateSources);
      const content = document.createElement('span'); const brand = document.createElement('span'); brand.className = 'source-brand';
      if (source.mark) brand.textContent = source.mark;
      else { const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.classList.add('icon'); const use = document.createElementNS('http://www.w3.org/2000/svg', 'use'); use.setAttribute('href', `#i-${source.icon || 'file'}`); svg.append(use); brand.append(svg); }
      const title = document.createElement('strong'); title.textContent = source.name;
      const caption = document.createElement('small'); caption.textContent = source.description || (source.requires_credentials ? 'Требуется учётная запись' : 'Открытые акты');
      content.append(brand, title, caption);
      if (!source.supported) { const soon = document.createElement('small'); soon.className = 'soon'; soon.textContent = 'Скоро · пока пропускается'; content.append(soon); }
      label.append(input, content); $('source-cards').append(label);
    }
    for (const [key, title] of Object.entries(options.ner.fields)) {
      const label = document.createElement('label'); const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'ner-field'; input.value = key; input.checked = key !== 'region';
      const text = document.createElement('span'); text.textContent = title; label.append(input, text); $('ner-fields').append(label);
    }
    ready = true; updateSources(); updateNer();
  } catch (error) { reportError(error.message); }
  await refresh();
}
async function refresh() {
  try { render(await api('/api/status')); }
  catch { reportError('Нет связи с приложением. Проверьте, что окно с сообщениями остаётся открытым.'); }
}
async function poll() { await refresh(); setTimeout(poll, 1000); }
initialize().then(() => setTimeout(poll, 1000));
