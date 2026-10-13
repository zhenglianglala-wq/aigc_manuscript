export class ApiError extends Error {
  constructor(public status:number,public code:string,message:string){super(message);this.name='ApiError';}
}
export async function api<T>(path:string,method='GET',body?:unknown,signal?:AbortSignal):Promise<T>{
  let response:Response;
  try { response=await fetch(`/api${path}`,{method,signal,headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}); }
  catch(error){ if(error instanceof DOMException && error.name==='AbortError') throw error; throw new ApiError(0,'OFFLINE','无法连接本地服务，请检查后端是否已启动。输入已保留。'); }
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new ApiError(response.status,data.error?.code??'REQUEST_FAILED',data.error?.message??(response.status===422?'输入不符合要求，请检查字段。':`操作失败 (${response.status})`));}
  if(response.status===204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function download(path:string,fallbackName:string){
  const response=await fetch(`/api${path}`);
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new ApiError(response.status,data.error?.code??'EXPORT_FAILED',data.error?.message??'导出失败，请先完成时间轴。');}
  const blob=await response.blob(); const url=URL.createObjectURL(blob); const a=document.createElement('a');
  a.href=url;a.download=fallbackName;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
