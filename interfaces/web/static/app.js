'use strict';
const $ = id => document.getElementById(id);
let choosingFolder = false;
const token = document.querySelector('meta[name="app-token"]').content;
const phases = {
  idle:['Всё готово к запуску','Документы появятся здесь после начала выгрузки.'],
  starting:['Запускаем Chromium','Подготавливаем новую сессию.'],
  login:['Вход в источник','В режиме отладки подтверждения можно пройти в окне Chromium.'],
  home:['Вход выполнен','Подготавливаем поиск закона.'],
  'search-start':['Ищем закон','Заполняем поисковый запрос.'],
  'query-filled':['Запрос подготовлен','Отправляем запрос в источник.'],
  'find-clicked':['Ожидаем результаты поиска','Это может занять некоторое время.'],
  results:['Закон найден','Открываем карточку документа.'],
  'first-card-opened':['Открываем связи документа','Ищем связанную судебную практику.'],
  'court-practice-high-courts':['Судебная практика найдена','Подготавливаем выгрузку актов высших судов.'],
  export:['Сохраняем документы','DOCX-файлы и таблица CSV сохраняются в папку загрузок.'],
  stopping:['Останавливаем выгрузку','Дождитесь завершения текущего действия и выхода из системы.'],
  'logging-out':['Выходим из источника','Завершаем серверную сессию.'],
  'logged-out':['Выход подтверждён','Завершаем работу браузера.'],
  'logout-unconfirmed':['Выход не подтверждён','Проверьте учётную запись вручную.'],
  done:['Выгрузка завершена','Откройте папку с документами и таблицей результатов.'],
  stopped:['Выгрузка остановлена','Уже сохранённые документы доступны в папке.'],
  failed:['Не удалось завершить выгрузку','Подробности указаны ниже.']
};
async function api(path, data) {
  const response = await fetch(path, {method:data === undefined ? 'GET':'POST', headers:{'X-App-Token':token,'Content-Type':'application/json'}, body:data === undefined ? undefined:JSON.stringify(data)});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Ошибка приложения.');
  return body;
}
function showError(message) { $('error').textContent=message; $('error').hidden=!message; }
function render(s) {
  const key=/^(saved|skipped):/.test(s.phase)?'export':s.phase;
  const [title, description]=phases[key] || ['Парсер работает','Ожидаем завершения текущего действия.'];
  $('phase').textContent=title; $('description').textContent=description;
  $('saved').textContent=s.saved; $('skipped').textContent=s.skipped;
  $('directory').textContent=s.directory;
  $('save-directory').value=s.save_directory;
  $('choose-folder').disabled=s.running || choosingFolder;
  $('badge').textContent=s.running?'В процессе':s.phase==='done'?'Готово':s.phase==='idle'?'Ожидание':'Завершено';
  $('settings').disabled=s.running; $('start').disabled=s.running || choosingFolder;
  $('stop').hidden=!s.running; $('stop').disabled=['stopping','logging-out'].includes(s.phase);
  document.querySelector('.result-card').classList.toggle('busy',s.running);
  $('status-icon').textContent=s.phase==='done'?'✓':s.phase==='failed'?'!':'↓';
  $('logout').textContent=s.logout===true?'Выход из источника подтверждён.':s.logout===false?'Выход не подтверждён. Проверьте серверную сессию вручную.':'';
  $('transport-summary').textContent=s.phase==='done'?`Текст через HTTP: ${s.http_texts || 0}; через браузер: ${s.browser_texts || 0}.`:'';
  showError(s.error);
}
$('parser-form').addEventListener('submit', async event=>{
  event.preventDefault(); $('start').disabled=true;
  try {
    const result=await api('/api/start',{login:$('login').value,password:$('password').value,law:$('law').value,debug:$('debug').checked,overwrite:$('overwrite').checked,transport:$('hybrid').checked?'hybrid':'browser'});
    $('password').value=''; render(result);
  } catch(error) { showError(error.message); $('start').disabled=false; }
});
$('show-password').addEventListener('click',()=>{
  const visible=$('password').type==='password';
  $('password').type=visible?'text':'password';
  $('show-password').textContent=visible?'Скрыть':'Показать';
  $('show-password').setAttribute('aria-label',visible?'Скрыть пароль':'Показать пароль');
  $('show-password').setAttribute('aria-pressed',String(visible));
});
$('choose-folder').addEventListener('click',async()=>{
  choosingFolder=true; $('choose-folder').disabled=true; $('start').disabled=true;
  try{render(await api('/api/choose-folder',{}));}catch(error){showError(error.message);}
  finally{choosingFolder=false; $('choose-folder').disabled=false; await refresh();}
});
$('stop').addEventListener('click',async()=>{try{render(await api('/api/stop',{}));}catch(error){showError(error.message);}});
$('open-folder').addEventListener('click',async()=>{try{await api('/api/open-folder',{});}catch(error){showError(error.message);}});
async function refresh(){try{render(await api('/api/status'));}catch{showError('Нет связи с приложением. Проверьте, что локальный сервер запущен.');}}
async function poll(){await refresh(); setTimeout(poll,1000);}
poll();
