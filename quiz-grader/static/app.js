let unsaved = new Set();
for (const form of document.querySelectorAll('.draft')) {
  let timer, running = false, revision = 0;
  const toggle = form.querySelector('.review-toggle');
  let reviewed = toggle.getAttribute('aria-pressed') === 'true';
  function showReview(value) {
    reviewed = value;
    toggle.setAttribute('aria-pressed', String(value));
    toggle.textContent = value ? '✓ Newly Graded' : toggle.dataset.baseStatus;
    form.closest('article').dataset.complete = String(value);
    const counter = document.querySelector('#completion');
    counter.textContent = `${document.querySelectorAll('article[data-complete="true"]').length} / ${counter.dataset.total} newly graded`;
  }
  const status = form.querySelector('.save-status');
  async function save() {
    clearTimeout(timer);
    if (running) return;
    if (!form.reportValidity()) { status.textContent = 'Check the score; draft not saved'; return; }
    running = true;
    const sent = revision;
    status.textContent = 'Saving…';
    try {
      const response = await fetch(form.dataset.url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf]').content}, body:JSON.stringify({fingerprint:form.dataset.fingerprint, score:form.elements.score.value, comment:form.elements.comment.value, reviewed})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Save failed. Reload after preserving your draft.');
      if (sent === revision) {
        unsaved.delete(form);
        status.textContent = reviewed ? 'Saved locally · ready for upload' : 'Saved locally · not queued for upload';
        form.closest('article').dataset.complete = String(result.complete);
        const counter = document.querySelector('#completion');
        counter.textContent = `${document.querySelectorAll('article[data-complete="true"]').length} / ${counter.dataset.total} newly graded`;
      }
    } catch (error) { status.textContent = error.message || 'Could not save. Try Save draft again.'; }
    finally { running = false; if (sent !== revision) save(); }
  }
  toggle.addEventListener('click', () => {
    if (!reviewed && (!form.elements.score.value || !form.reportValidity())) { status.textContent='Enter a valid score first'; return; }
    showReview(!reviewed); revision++; unsaved.add(form); save();
  });
  form.addEventListener('input', () => { showReview(false); revision++; unsaved.add(form); status.textContent='Unsaved changes'; clearTimeout(timer); timer=setTimeout(save, 450); });
  form.addEventListener('submit', event => { event.preventDefault(); save(); });
}
window.addEventListener('beforeunload', event => { if (unsaved.size) { event.preventDefault(); event.returnValue=''; } });
for (const form of document.querySelectorAll('form[action="/load"]')) form.addEventListener('submit', () => { const button=form.querySelector('button'); button.disabled=true; button.textContent='Loading…'; });
const board = document.querySelector('.comment-board');
if (board) {
  let activeFeedback = null;
  const message = document.querySelector('#board-status');
  document.addEventListener('focusin', event => {
    if (event.target.matches('.draft textarea') && !event.target.matches(':disabled')) activeFeedback = event.target;
  });
  function insert(text) {
    if (!activeFeedback || activeFeedback.matches(':disabled')) { message.textContent = "Focus a student's feedback first."; return; }
    const field = activeFeedback;
    if (field.value.length - (field.selectionEnd-field.selectionStart) + text.length > field.maxLength) { message.textContent = 'Feedback would exceed 10,000 characters.'; return; }
    field.setRangeText(text, field.selectionStart, field.selectionEnd, 'end');
    field.focus();
    field.dispatchEvent(new Event('input', {bubbles:true}));
    message.textContent = 'Inserted into the active feedback. Draft autosave will follow.';
  }
  async function update(text, slot) {
    try {
      const response = await fetch(board.dataset.url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf]').content},body:JSON.stringify({text,slot})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save the board.');
      render(result.board);
      message.textContent = 'Comment board saved locally.';
    } catch (error) { message.textContent = error.message; }
  }
  function render(comments) {
    const container = document.querySelector('#board-slots');
    container.replaceChildren();
    for (let slot=1; slot<=9; slot++) {
      const row=document.createElement('div'); row.className='board-slot'; row.dataset.slot=slot;
      const button=document.createElement('button'); button.type='button'; button.className='insert-comment'; button.disabled=!comments[slot];
      const number=document.createElement('kbd'); number.textContent=slot;
      const label=document.createElement('span'); label.textContent=comments[slot] || 'Empty slot'; button.append(number,label); row.append(button);
      if (comments[slot]) {
        const actions=document.createElement('div'); actions.className='board-actions';
        for (const [name, css] of [['Edit','edit-comment'],['Remove','remove-comment']]) { const action=document.createElement('button'); action.type='button'; action.className=css+' text-button'; action.textContent=name; actions.append(action); }
        row.append(actions);
      }
      container.append(row);
    }
  }
  board.addEventListener('click', event => {
    const row=event.target.closest('.board-slot'); if (!row) return;
    const slot=Number(row.dataset.slot), text=row.querySelector('.insert-comment span').textContent;
    if (event.target.closest('.insert-comment')) insert(text);
    if (event.target.closest('.remove-comment')) update('',slot);
    if (event.target.closest('.edit-comment') && !row.querySelector('textarea')) {
      const editor=document.createElement('textarea'); editor.className='board-editor'; editor.value=text; editor.maxLength=10000; editor.setAttribute('aria-label',`Edit comment ${slot}`);
      const save=document.createElement('button'); save.type='button'; save.textContent='Save'; save.className='text-button';
      const cancel=document.createElement('button'); cancel.type='button'; cancel.textContent='Cancel'; cancel.className='text-button';
      save.onclick=()=>{if(editor.value.trim()) update(editor.value,slot); else message.textContent='Use Remove to clear this slot.';};
      cancel.onclick=()=>{editor.remove();save.remove();cancel.remove();};
      row.append(editor,save,cancel);editor.focus();
    }
  });
  document.querySelectorAll('.save-to-board').forEach(button=>button.addEventListener('click',()=>update(button.closest('form').elements.comment.value)));
  document.addEventListener('keydown', event => {
    if (event.ctrlKey && event.shiftKey && !event.metaKey && !event.altKey && /^Digit[1-9]$/.test(event.code) && event.target.matches('.draft textarea')) {
      event.preventDefault();
      const button=board.querySelector(`[data-slot="${event.code.slice(-1)}"] .insert-comment`);
      if (!button.disabled) insert(button.querySelector('span').textContent); else message.textContent='That comment slot is empty.';
    }
  });
}
for (const form of document.querySelectorAll('.publish-start, .publish-confirm')) {
  form.addEventListener('submit', event => {
    if (unsaved.size) { event.preventDefault(); alert('Wait for all drafts to save before reviewing an upload.'); return; }
    const button=form.querySelector('button'); button.disabled=true; button.textContent='Checking Canvas…';
  });
}
for (const form of document.querySelectorAll('.publish-confirm')) {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button=form.querySelector('button');
    const started=Date.now(); let elapsed=0;
    button.disabled=true;
    const timer=setInterval(()=>{ elapsed=Math.floor((Date.now()-started)/1000); button.textContent=`Sending to Canvas… ${elapsed}s`; },1000);
    const status=document.createElement('p'); status.className='hint'; status.setAttribute('role','status'); status.textContent='Canvas may take a moment. This page is still working; do not submit again.'; form.append(status);
    try {
      const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{'X-Requested-With':'fetch'}});
      const html=await response.text();
      clearInterval(timer); document.open(); document.write(html); document.close();
    } catch (error) { clearInterval(timer); button.disabled=false; button.textContent='Retry upload'; status.textContent='The browser connection ended before results arrived. Check the upload review before retrying.'; }
  });
}
(function(){
  const pane=document.querySelector('.grading');
  if(!pane) return;
  let navFocus=false;
  const responses=()=>Array.from(pane.querySelectorAll('.response'));
  const questions=()=>Array.from(document.querySelectorAll('.question-link'));
  function focusResponse(index){
    const rows=responses(); if(!rows.length)return;
    index=Math.max(0,Math.min(rows.length-1,index)); const row=rows[index];
    row.scrollIntoView({block:'center'}); row.focus({preventScroll:true}); navFocus=true;
    const field=row.querySelector('textarea:not(:disabled)'); if(field){field.focus(); field.scrollIntoView({block:'end'});}
  }
  function moveQuestion(delta){
    const links=questions(), current=links.findIndex(a=>a.classList.contains('active')); if(current<0)return;
    const next=Math.max(0,Math.min(links.length-1,current+delta)); if(next===current)return;
    const student=document.activeElement?.closest('.response')?.dataset.student;
    const url=new URL(links[next].href,location.href); if(student) url.searchParams.set('student',student);
    location.href=url;
  }
  pane.addEventListener('focusin',e=>{if(e.target.matches('textarea,input'))navFocus=false;});
  document.addEventListener('keydown',e=>{
    const editing=e.target.matches('textarea,input,[contenteditable="true"]');
    if(e.key==='Escape' && editing){e.preventDefault(); const row=e.target.closest('.response'); if(row){row.focus(); navFocus=true;} return;}
    if(editing || !navFocus)return;
    if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault(); const rows=responses(); const i=rows.indexOf(document.activeElement.closest('.response')); focusResponse(i+(e.key==='ArrowDown'?1:-1));}
    if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault(); moveQuestion(e.key==='ArrowRight'?1:-1);}
  });
  document.addEventListener('click',e=>{if(e.target.closest('.response'))navFocus=true;});
})();

(function(){ const id=new URLSearchParams(location.search).get('student'); if(!id)return; const row=document.querySelector(`.response[data-student="${CSS.escape(id)}"]`); if(row){row.scrollIntoView({block:'center'}); row.focus();} })();
