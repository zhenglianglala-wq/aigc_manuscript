import {useEffect,useState} from 'react';
import {Field,Tag} from '../../components/UI';
import type {PhotoField,PhotoProject,PhotoPrompt} from './types';
import {photoFields,photoLabels} from './types';
type Draft={base:number;values:Record<PhotoField,string>;negative:string};
const initial=(project:PhotoProject):Draft=>({base:project.current_revision,values:Object.fromEntries(photoFields.map(f=>[f,project.prompt?.[f]??''])) as Record<PhotoField,string>,negative:project.prompt?.negative_constraints.join('\n')??''});
export default function PhotoPromptEditor({project,busy,onSave,onConfirm,onCopy,onExport}:{project:PhotoProject;busy:boolean;onSave:(changes:Partial<PhotoPrompt>,base:number)=>Promise<boolean>;onConfirm:()=>void;onCopy:()=>void;onExport:(format:'json'|'markdown')=>void}){
 const key=`studio:photo-prompt:${project.id}`;
 const [draft,setDraft]=useState<Draft>(()=>{try{const raw=localStorage.getItem(key);if(raw){const saved=JSON.parse(raw);if(saved.values&&typeof saved.negative==='string'&&Number.isInteger(saved.base))return saved}}catch{}return initial(project)});
 useEffect(()=>{if(!localStorage.getItem(key))setDraft(initial(project))},[project.current_revision,project.prompt,key]);
 const p=project.prompt!;
 const dirty=photoFields.some(f=>draft.values[f]!==p[f])||draft.negative!==p.negative_constraints.join('\n');
 const stale=draft.base!==project.current_revision;
 const setField=(f:PhotoField,value:string)=>{const next={...draft,values:{...draft.values,[f]:value}};setDraft(next);localStorage.setItem(key,JSON.stringify(next))};
 return <section><div className="section-heading"><h2>结构化照片 Prompt</h2><div className="photo-config-meta"><Tag tone={p.confirmed?'success':'warning'}>{p.confirmed?'Prompt 已确认':'需要确认'}</Tag>{p.generation_mode==='fixture'&&<Tag tone="warning">示例文字</Tag>}{dirty&&<Tag>未保存草稿</Tag>}</div></div>
 <p className="photo-prompt-revision">版本 {project.current_revision} · 保存修改后，需要重新确认才能生成图片。</p>
 {dirty&&stale&&<p className="notice">草稿基于版本 {draft.base}，当前项目已更新。请先比较并恢复当前内容，旧草稿不会覆盖新版本。</p>}
 <form onSubmit={async e=>{e.preventDefault();if(await onSave({...draft.values,negative_constraints:draft.negative.split('\n').map(s=>s.trim()).filter(Boolean)},draft.base))localStorage.removeItem(key)}}>
 <div className="photo-prompt-fields">{photoFields.map(f=><Field key={f} label={photoLabels[f]}><textarea rows={3} maxLength={f==='subject'||f==='environment'?3000:f==='details'?4000:2000} value={draft.values[f]??''} onChange={e=>setField(f,e.target.value)} required={f!=='details'}/></Field>)}</div>
 <Field label="避免出现的内容" hint="每行一项。作为约束元数据保存；本版图片接口不会假定模型支持独立 negative_prompt。"><textarea rows={3} value={draft.negative} onChange={e=>{const next={...draft,negative:e.target.value};setDraft(next);localStorage.setItem(key,JSON.stringify(next))}}/></Field>
 <div className="actions"><button className="primary" disabled={busy||!dirty||stale}>保存照片 Prompt</button>{dirty&&<button type="button" onClick={()=>{localStorage.removeItem(key);setDraft(initial(project))}}>恢复已保存 Prompt</button>}</div></form>
 <div className="section-heading" style={{marginTop:30}}><h2>连续生成 Prompt</h2><Tag>已保存版本 {project.current_revision}</Tag></div><div className="photo-prompt-preview">{p.compiled_prompt}</div>
 <div className="actions"><button disabled={busy||dirty||p.confirmed} className="primary" onClick={onConfirm}>确认照片 Prompt</button><button onClick={onCopy}>复制照片 Prompt</button><button disabled={busy} onClick={()=>onExport('json')}>导出照片 JSON</button><button disabled={busy} onClick={()=>onExport('markdown')}>导出照片 Markdown</button></div>
 {dirty&&<p className="photo-small-info">请先保存草稿；复制与导出使用上方已保存版本，不包含未保存编辑。</p>}
 </section>;
}
