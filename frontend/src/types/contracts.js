/** @typedef {{id:number,code:string,team:string,before:number|null,after:number|null,note:string}} Pair */
/** @typedef {{id:number,name:string,team:string,state:string,result:object,error:string}} Evaluation */
/** @typedef {{id:number,plan_id:number|null,plan_version:number|null,hypothesis_id:number|null,evaluation_id:number|null,decision:string,note:string,status:string,evidence:object|null}} Adoption */
/** @typedef {{id:number,name:string,state:'pending'|'running'|'available'|'failed',alpha:number,sample:Pair[],sample_checksum:string,design_checksum:string,result:object|null,error:string,attempts:number,version:number,attempt_log:object[],hypotheses:object[],family_size:number,overlap:object,published:boolean}} Plan */
