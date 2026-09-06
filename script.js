document.addEventListener('DOMContentLoaded',()=>{
 const navToggle=document.querySelector('.nav-toggle'); const nav=document.querySelector('#mainNav');
 if(navToggle&&nav){navToggle.addEventListener('click',()=>{const open=nav.classList.toggle('open');navToggle.setAttribute('aria-expanded',open?'true':'false');navToggle.innerHTML=open?'<i class="fa-solid fa-xmark"></i>':'<i class="fa-solid fa-bars"></i>';});nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{nav.classList.remove('open');navToggle.setAttribute('aria-expanded','false');navToggle.innerHTML='<i class="fa-solid fa-bars"></i>';}));}
 const sidebar=document.querySelector('#adminSidebar'); const openBtn=document.querySelector('.admin-mobile-toggle'); const closeBtn=document.querySelector('.admin-close'); const overlay=document.querySelector('#adminOverlay');
 const toggleAdmin=(open)=>{if(!sidebar)return;sidebar.classList.toggle('open',open);overlay&&overlay.classList.toggle('open',open);document.body.style.overflow=open?'hidden':'';};
 openBtn&&openBtn.addEventListener('click',()=>toggleAdmin(true)); closeBtn&&closeBtn.addEventListener('click',()=>toggleAdmin(false)); overlay&&overlay.addEventListener('click',()=>toggleAdmin(false));
 document.querySelectorAll('input[type=file]').forEach(input=>{
   const preview=input.closest('.upload-zone-wrap, .logo-upload-box')?.querySelector('[data-upload-preview]');
   const zone=input.closest('[data-upload-zone]');
   const clear=preview?.querySelector('[data-upload-clear]');
   const showFile=(file)=>{
     if(!file)return;
     const allowed=['image/jpeg','image/png','image/webp'];
     if(!allowed.includes(file.type)){alert('Please choose a JPG, PNG or WEBP image.');input.value='';if(preview)preview.hidden=true;return;}
     if(file.size>5*1024*1024){alert('Image is larger than 5 MB. Please choose a smaller file.');input.value='';if(preview)preview.hidden=true;return;}
     if(preview){const img=preview.querySelector('img');const name=preview.querySelector('[data-upload-name]');const meta=preview.querySelector('[data-upload-meta]');if(img)img.src=URL.createObjectURL(file);if(name)name.textContent=file.name;if(meta)meta.textContent=(file.size/1024/1024).toFixed(2)+' MB · Ready to upload';preview.hidden=false;}
   };
   input.addEventListener('change',()=>showFile(input.files?.[0]));
   clear?.addEventListener('click',e=>{e.preventDefault();input.value='';if(preview)preview.hidden=true;});
   if(zone){['dragenter','dragover'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.add('is-dragover')}));['dragleave','drop'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.remove('is-dragover')}));zone.addEventListener('drop',e=>{const file=e.dataTransfer.files?.[0];if(!file)return;try{const dt=new DataTransfer();dt.items.add(file);input.files=dt.files;showFile(file);}catch(_){showFile(file);}});}
 });
 document.querySelectorAll('[data-password-toggle]').forEach(btn=>btn.addEventListener('click',()=>{const input=document.getElementById(btn.dataset.passwordToggle);if(!input)return;const show=input.type==='password';input.type=show?'text':'password';btn.setAttribute('aria-label',show?'Hide password':'Show password');btn.innerHTML=show?'<i class="fa-regular fa-eye-slash"></i>':'<i class="fa-regular fa-eye"></i>';}));
 const search=document.querySelector('[data-table-search]'); if(search){search.addEventListener('input',()=>{const q=search.value.toLowerCase();document.querySelectorAll('[data-search-row]').forEach(row=>row.style.display=row.innerText.toLowerCase().includes(q)?'':'none');});}
});
/* Mobile-safe product image upload: upload immediately after selection so
   Android/Chrome temporary file handles cannot disappear before submit. */
(function(){
  const productForms=document.querySelectorAll('form.product-editor');
  productForms.forEach(form=>{
    const input=form.querySelector('input[type=file][name=image]');
    const hidden=form.querySelector('[data-uploaded-image]');
    const zone=input?.closest('[data-upload-zone]');
    const preview=form.querySelector('[data-upload-preview]');
    const status=zone?.querySelector('[data-upload-status]');
    if(!input || !hidden) return;
    let uploading=false;
    const csrf=form.querySelector('input[name=csrf_token]')?.value || '';
    const originalChange=input.onchange;
    const setStatus=(text)=>{if(status)status.textContent=text;};
    const uploadNow=async(file)=>{
      if(!file) return;
      uploading=true;
      zone?.classList.add('uploading');
      zone?.classList.remove('uploaded');
      setStatus('Uploading image securely…');
      const data=new FormData();
      data.append('csrf_token',csrf);
      data.append('image',file,file.name);
      try{
        const res=await fetch('/admin/products/upload-image',{method:'POST',body:data,credentials:'same-origin'});
        let payload={};
        try{payload=await res.json();}catch(_){payload={message:'The server returned an invalid upload response.'};}
        if(!res.ok || !payload.ok) throw new Error(payload.message || 'Image upload failed.');
        hidden.value=payload.filename;
        zone?.classList.add('uploaded');
        if(preview){preview.classList.add('is-uploaded');}
        setStatus('Image uploaded ✓ · Ready to save product');
      }catch(err){
        hidden.value='';
        input.value='';
        zone?.classList.remove('uploaded');
        setStatus('Upload failed — tap to choose the image again.');
        alert(err.message || 'Could not upload the image. Please try again.');
      }finally{
        uploading=false;
        zone?.classList.remove('uploading');
      }
    };
    input.addEventListener('change',()=>{
      hidden.value='';
      const file=input.files?.[0];
      if(file) uploadNow(file);
    });
    form.querySelector('[data-upload-clear]')?.addEventListener('click',()=>{
      hidden.value='';
      input.disabled=false;
      zone?.classList.remove('uploaded','uploading');
      setStatus('Tap to choose · JPG, PNG or WEBP · Maximum 5 MB');
    });
    form.addEventListener('submit',(e)=>{
      if(uploading){
        e.preventDefault();
        setStatus('Please wait — the image is still uploading…');
        return;
      }
      /* The original browser file is no longer needed after immediate upload. */
      if(hidden.value){input.disabled=true;}
    });
  });
})();

/* Mobile-safe store logo upload. Upload immediately after selection so the
   final settings form never depends on Android/Chrome temporary file handles. */
(function(){
  const form=document.querySelector('form[data-settings-form]');
  if(!form) return;
  const input=form.querySelector('input[type=file][name=logo]');
  const hidden=form.querySelector('[data-uploaded-logo]');
  const preview=form.querySelector('[data-upload-preview]');
  const clear=form.querySelector('[data-upload-clear]');
  const csrf=form.querySelector('input[name=csrf_token]')?.value || '';
  const zone=input?.closest('.settings-logo-picker, .logo-upload-box');
  if(!input || !hidden) return;
  let uploading=false;
  const status=zone?.querySelector('[data-upload-meta]');
  const nameEl=zone?.querySelector('[data-upload-name]');
  const setPreview=(file, url, uploaded=false)=>{
    if(!preview) return;
    const img=preview.querySelector('img');
    if(img && (url || file)) img.src=url || URL.createObjectURL(file);
    if(nameEl && file) nameEl.textContent=file.name;
    if(status && file) status.textContent=(file.size/1024/1024).toFixed(2)+' MB · '+(uploaded?'Uploaded ✓':'Ready to upload');
    preview.hidden=false;
    preview.classList.toggle('is-uploaded',uploaded);
  };
  const uploadNow=async(file)=>{
    if(!file) return;
    const allowed=['image/jpeg','image/png','image/webp'];
    if(!allowed.includes(file.type)){ alert('Please choose a JPG, PNG or WEBP logo.'); input.value=''; return; }
    if(file.size>5*1024*1024){ alert('Logo is larger than 5 MB. Please choose a smaller file.'); input.value=''; return; }
    uploading=true;
    if(status) status.textContent='Uploading logo securely…';
    const data=new FormData();
    data.append('csrf_token',csrf);
    data.append('logo',file,file.name);
    try{
      const res=await fetch('/admin/settings/upload-logo',{method:'POST',body:data,credentials:'same-origin'});
      let payload={};
      try{payload=await res.json();}catch(_){payload={message:'The server returned an invalid upload response.'};}
      if(!res.ok || !payload.ok) throw new Error(payload.message || 'Logo upload failed.');
      hidden.value=payload.filename;
      setPreview(file,payload.url,true);
      input.disabled=true;
      if(status) status.textContent=(file.size/1024/1024).toFixed(2)+' MB · Uploaded ✓ · Ready to save';
      /* Update any current-logo image on the page immediately. */
      const currentImg=form.querySelector('.settings-logo-preview img');
      if(currentImg) currentImg.src=payload.url;
    }catch(err){
      hidden.value=''; input.value='';
      if(status) status.textContent='Upload failed — tap to choose the logo again.';
      alert(err.message || 'Could not upload the logo. Please try again.');
    }finally{ uploading=false; }
  };
  input.addEventListener('change',()=>uploadNow(input.files?.[0]));
  clear?.addEventListener('click',e=>{
    e.preventDefault();
    hidden.value=''; input.value=''; input.disabled=false;
    if(preview) preview.hidden=true;
    if(status) status.textContent='Ready to upload';
  });
  form.addEventListener('submit',e=>{
    if(uploading){ e.preventDefault(); if(status) status.textContent='Please wait — the logo is still uploading…'; return; }
    if(hidden.value) input.disabled=true;
  });
})();

// Modern cart quantity controls
(function () {
  document.querySelectorAll('[data-qty-minus], [data-qty-plus]').forEach(function (button) {
    button.addEventListener('click', function () {
      var wrap = button.closest('.quantity-control');
      if (!wrap) return;
      var input = wrap.querySelector('input[type="number"]');
      if (!input) return;
      var current = parseInt(input.value || '1', 10);
      var min = parseInt(input.min || '1', 10);
      var max = parseInt(input.max || '999999', 10);
      if (button.hasAttribute('data-qty-minus')) current -= 1;
      else current += 1;
      current = Math.max(min, Math.min(max, current));
      input.value = current;
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
  });
})();
