import {Children,cloneElement,isValidElement,useId} from 'react';
import type {ReactElement,ReactNode} from 'react';
export function Field({label,children,hint}:{label:string;children:ReactNode;hint?:string}){
 const id=useId();
 const controls=Children.map(children,child=>{
  if(!isValidElement(child)||!['input','textarea','select'].includes(String(child.type)))return child;
  return cloneElement(child as ReactElement<{'aria-labelledby'?:string;'aria-describedby'?:string}>,{'aria-labelledby':`${id}-label`,...(hint?{'aria-describedby':`${id}-hint`}:{})});
 });
 return <label className="field"><span id={`${id}-label`}>{label}</span>{controls}{hint&&<small id={`${id}-hint`}>{hint}</small>}</label>;
}
export function Empty({title,children}:{title:string;children?:ReactNode}){return <div className="empty"><span className="empty-mark" aria-hidden="true">✦</span><h2>{title}</h2>{children&&<p>{children}</p>}</div>;}
export function Tag({children,tone=''}:{children:ReactNode;tone?:string}){return <span className={`tag ${tone}`}>{children}</span>;}
export function Detail({title,children,open=false}:{title:string;children:ReactNode;open?:boolean}){return <details open={open||undefined}><summary>{title}</summary><div className="detail-body">{children}</div></details>;}
export function Pretty({value}:{value:unknown}){return <pre className="pretty">{typeof value==='string'?value:JSON.stringify(value,null,2)}</pre>;}
