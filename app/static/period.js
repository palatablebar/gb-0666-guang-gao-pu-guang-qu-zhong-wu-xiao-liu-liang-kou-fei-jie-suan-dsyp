const feedback=document.querySelector('#period-feedback');
function setBusy(form,busy){form.querySelectorAll('button').forEach(b=>b.disabled=busy);}
async function post(url,body){
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.detail?.message||value.message||'操作失败，请重试');
  return value;
}
function formPayload(form,extra){
  const values=new FormData(form);
  const body={...extra};
  for(const [key,val] of values.entries()){
    if(key!=='text'||String(val).trim())body[key]=val;
  }
  return body;
}
async function handle(form,url,extra){
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(form.dataset.busy==='1')return;
    form.dataset.busy='1';setBusy(form,true);feedback.textContent='处理中…';
    try{
      const value=await post(url,formPayload(form,extra));
      const id=value.supplement_id?value.supplement_id:'';
      location.href=location.pathname+(id?('?supplement_id='+encodeURIComponent(id)):'');
    }catch(error){
      feedback.textContent=error.message+'（旧版本与已保存记录保持不变）';
    }finally{
      form.dataset.busy='0';setBusy(form,false);
    }
  });
}
handle(document.querySelector('#close-form'),'/api/periods/close',{});
handle(document.querySelector('#supplement-form'),'/api/periods/supplements',{});
const review=document.querySelector('#supplement-review');
if(review)review.addEventListener('submit',async event=>{
  event.preventDefault();
  try{
    await post('/api/periods/supplements/'+review.dataset.id+'/review',{revision:Number(review.dataset.version),decision:new FormData(review).get('decision')});
    location.reload();
  }catch(error){feedback.textContent=error.message;}
});
