/** @typedef {{id:number,code:string,name:string,starts_at:string,ends_at:string,a_ratio:number,hypothesis:string,exposures:number,identity?:object}} Experiment */
/** @typedef {{id:number,experiment_id:number,user_key:string,group:'A'|'B',kind:'exposure'|'activation',occurred_at:string,identity?:string}} TrialEvent */
/** @typedef {{id:number,experiment_id:number,state:string,result:object,snapshot:object,rationale:string,action:string,published_at:string}} Decision */
/** @typedef {{id:number,state:string,source:string,note:string,error:string,created_by:string,created:string,finished:string,processed_items:number,failed_items:number,applied_merges:number,identity_version_before:number,identity_version_after:number,items:Array<{id:number,a_key:string,b_key:string,state:string,message:string}>}} AliasJob */
/** @typedef {{raw_exposed_a:number,raw_exposed_b:number,raw_exposed_total:number,n_a:number,n_b:number,activated_a:number,activated_b:number,dedup_exposed_total:number,polluted_count:number,polluted:Array,identity_version:number}} IdentityReport */
export const CONTRACT_VERSION='2.0';
