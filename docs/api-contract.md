# API contract v1

All APIs use JSON unless exports. Error: `{ "error": {"code":"...","message":"...","retryable":false} }`. IDs are UUID strings. Revision is an integer (initial 1). API prefix `/api`; health `/health`. Fixture mode is explicitly synthetic, no external call.

## Project
`POST /api/projects`: `{ "title":"optional", "brief":{"description":"...","duration_seconds":15,"aspect_ratio":"9:16","style":"电影感","language":"zh","audience":"大众","must_include":[],"must_avoid":[]} }`.
Returns Project: `{id,title,brief,current_revision:1,document:{story:null,beats:[],shots:[]},created_at,updated_at}`. List `GET /api/projects` returns array. GET by id same shape. PATCH requires `{base_revision:1,title?:string,brief?:Brief}`. DELETE cascades.
Document story: `{title,synopsis,assumptions:[],characters:[{id,name,description}],scenes:[{id,name,description}],confirmed:false}`. Beat: `{start_second:0,end_second:1,visual,action,camera,dialogue,sound,prompt,character_ids:[],scene_id,continuity}`. Shot: `{id,start_second,end_second,prompt,beat_seconds:[],continuity}`.
`POST /api/projects/{id}/story/confirm`: `{base_revision:N}`. PATCH `/beats/{second}`: `{base_revision:N,changes:{visual?:...,action?:...,camera?:...,dialogue?:...,sound?:...,continuity?:...}}`. Compiles prompts atomically; returns Project.
GET revisions returns array `{version,parent_version,source,document,created_at}`. POST `/revisions/{version}/restore`: `{base_revision:N}` returns Project.

## Tasks and candidates
POST `/api/projects/{id}/runs`: `{kind:"expand"|"timeline"|"rewrite"|"check",base_revision:N,idempotency_key:"unique",instruction:"optional",start_second:0,end_second:5,locked_fields:[],approval_id:null}`. Returns Run `{id,project_id,kind,status,base_revision,steps:[],proposal_id:null,result:null,error:null,usage:{input_tokens:null,output_tokens:null,cost:null,cost_status:"unknown"},mode:"fixture",created_at}`. Poll GET `/api/runs/{id}` until terminal succeeded/failed/cancelled/interrupted. Cancel POST `/cancel`.
Expansion/timeline/rewrite produce candidate, never silently apply. GET `/projects/{id}/proposals` array: `{id,project_id,base_revision,kind,status:"pending",document,diff,issues,created_at}`. POST `/api/proposals/{id}/apply` `{base_revision:N}` returns Project; reject stale base with 409. POST `/dismiss` empty object returns Proposal.
GET `/projects/{id}/checks`: `{issues:[],valid:true}`. GET exports `?format=json|markdown|csv` attachment, rejects incomplete timeline. Check run succeeds with result checks; no proposal.

## Conversation and memory
GET/POST `/projects/{id}/conversations`; POST `{title:"讨论"}`. Returns `{id,project_id,title,created_at}`. GET `/conversations/{id}/messages` array `{id,conversation_id,project_id,role,content,references:[],created_at,run_id}`.
POST messages `{content:"...",idempotency_key:"unique",references:[{type:"beat",id:"0"}],intent:"chat"|"rewrite",start_second:0,end_second:5,approval_id:null}` -> Run; user message stored immediately. Rewrite intent produces candidate; chat only reply. References types `beat`, `shot`, `revision`, `message` checked against project. DELETE message/conversation invalidates dependent context and memory sources.
GET `/runs/{id}/context`: `{id,project_id,revision,message_ids:[],memory_ids:[],reference_ids:[],summary:{text,source_message_ids:[],method:"extractive"},messages:[],memories:[],valid:true}`. Deleted sources redact affected snapshot content. Historical metadata stays auditable.
GET memories `?project_id=ID` gives project plus user scope; no project parameter gives user scope only. POST `{scope:"project"|"user",project_id:ID|null,content:"...",source_message_ids:[],source_revision:N|null}` creates candidate. PATCH `{content?:string,status?:"inactive",expected_version:N}` edits into candidate, requiring reconfirmation. POST `/{id}/confirm` `{expected_version:N}`. DELETE removes body, tombstones source messages, invalidates contexts. Shape `{id,scope,project_id,content,status,version,source_message_ids,source_revision,created_at,updated_at}`.

## Settings, approvals, metadata
GET/PATCH profile `{display_name,language,default_duration_seconds,default_aspect_ratio,default_style}`.
GET/PATCH `/settings/model`: `{mode:"fixture"|"openai-compatible",base_url,model,max_output_tokens:12000,temperature:0.7,input_price_per_million:null,output_price_per_million:null,price_date:null,key_present:false,paid_calls_enabled:false}`. Key and paid switch ONLY process environment, never API setters. Compatible protocol POST `base_url/chat/completions`, one JSON document response. Config validates HTTPS or loopback HTTP. Setting endpoint does not call upstream.
GET/POST approvals; POST `{project_id:ID,max_calls:1,accept_unknown_cost:true,budget:null,expires_in_minutes:60}`. Unknown price requires explicit acceptance. Shape `{id,project_id,max_calls,calls_used,accept_unknown_cost,budget,spent,expires_at,status}`; DELETE revoke. Each retry consumes approval call. Budget is conservative local preflight, no billing guarantee.
GET/POST `/projects/{id}/references`: `{url:"https://...",title:"...",prompt:"...",notes:"...",model:"..."}`. No network fetch. GET/POST feedback `{url:"https://...",model:"...",actual_prompt:"...",rating:1..5,notes:"...",revision:N}`.
POST `/backups` returns `{id,filename,created_at}`. GET `/backups/{id}/download` SQLite attachment. Backup contains local conversations and projects, no credentials; files only under data/backups.

All writes validate referenced entity ownership; version writes are transactional. Data dir env `DATA_DIR`; default `data`. Restart marks in-flight tasks interrupted. Default fixture output adapts brief deterministically but has no claim of AI quality.

## Additions frozen during implementation
Brief has `prompt_profile: "generic_text_to_video" | "motion_first_image_to_video"` (default generic). GET `/api/prompt-profiles` array `{id,label,version,source,verified:false}`. Shots include profile/version/unverified capability; document includes profile metadata and negative constraints separately. These are rule profiles, not vendor guarantees.
PATCH `/api/projects/{id}/story`: `{base_revision:N,changes:{title?,synopsis?,characters?,scenes?,assumptions?}}`. Returns Project; clears timeline and confirmed flag when story changes to avoid stale facts. GET `/api/projects/{id}/runs` array.

## Message erasure and independent artifacts
DELETE message/conversation redacts affected `Run.request.content/instruction/message_body` and `Run.result`, clears associated proposal copies, and marks proposals dismissed. Provenance-linked assistant echoes are redacted; derived memory bodies are tombstoned. Audit IDs/status/usage remain. Return includes `derived_outputs_redacted:true` and `retained_independent_artifacts:["applied_project_revisions","existing_backups"]`. Previously applied project versions are independent user artifacts, so deleting a message does not rewrite them; pre-existing backup copies are separately managed. This describes logical application deletion, not a forensic disk-erasure guarantee.
