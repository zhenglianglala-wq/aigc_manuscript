import {useEffect,useRef,useState} from 'react';
import type {ImageSettings} from './types';
import {Tag} from '../../components/UI';
export type ImageGenerationConfirmation={project_id:string;base_revision:number;prompt_source:'direct'|'project';prompt_text:string;direct_prompt?:string;settings:ImageSettings;approval_id:string|null;idempotency_key:string};
export default function PhotoGenerationDialog({request,busy,attempted,error,onCancel,onApprove}:{request:ImageGenerationConfirmation;busy:boolean;attempted:boolean;error:string;onCancel:()=>void;onApprove:(acceptUnknown:boolean)=>void}){
 const dialog=useRef<HTMLDialogElement>(null),[accepted,setAccepted]=useState(false);
 useEffect(()=>{const el=dialog.current;el?.showModal();return()=>el?.close()},[]);
 const price=request.settings.estimated_price_per_image,unknown=price===null;
 const unavailable=!request.settings.key_present||!request.settings.paid_calls_enabled||!request.settings.model||!request.settings.base_url;
 return <dialog ref={dialog} className="photo-generation-dialog" aria-labelledby="image-generation-title" onCancel={e=>{if(busy)e.preventDefault();else onCancel()}}>
  <div className="section-heading"><h2 id="image-generation-title">确认生成一张照片</h2><Tag>一次任务 · 1 张</Tag></div>
  <dl className="photo-confirmation-facts"><div><dt>模型</dt><dd>{request.settings.model||'未配置'}</dd></div><div><dt>尺寸</dt><dd>{request.settings.size}</dd></div><div><dt>服务</dt><dd>{request.settings.base_url||'未配置'}</dd></div><div><dt>Prompt 来源</dt><dd>{request.prompt_source==='direct'?'直接输入原文':`已确认项目版本 ${request.base_revision}`}</dd></div><div><dt>本次费用</dt><dd>{unknown?'未知':`估算 ${price} / 1 张`}</dd></div></dl>
  <h3>将发送的 Prompt</h3><div className="photo-confirmation-prompt">{request.prompt_text}</div>
  {request.approval_id?<p className="photo-small-info">使用已选的有效图片批准，消耗其中 1 次调用；不创建新批准。</p>:<p className="photo-small-info">点击确认后，为当前项目创建一次图片调用批准，再提交生成。估算费用采用配置价格，实际以服务商账单为准。</p>}
  {unknown&&!request.approval_id&&<label className="check"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)} disabled={busy||attempted}/>我接受本次费用未知，最多生成 1 张</label>}
  {unavailable&&<p className="notice">图片模型、服务地址、后端 IMAGE_API_KEY 或图片付费开关尚未完整配置，请先检查图片设置。</p>}
  {error&&<p className="notice" role="alert">{error}</p>}
  {attempted&&!busy&&error&&<p className="photo-small-info">提交未获确认，不代表任务未执行或未计费。请先刷新运行记录；系统不会自动再次生成。</p>}
  <div className="actions"><button autoFocus disabled={busy} onClick={onCancel}>{attempted?'关闭确认':'取消生成'}</button><button className="primary" disabled={busy||attempted||unavailable||(unknown&&!request.approval_id&&!accepted)} onClick={()=>onApprove(accepted)}>{busy?'正在提交…':request.approval_id?'使用已有批准并生成1张':'批准并生成1张'}</button></div>
 </dialog>;
}
