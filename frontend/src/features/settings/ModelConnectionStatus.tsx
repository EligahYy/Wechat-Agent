export function ModelConnectionStatus({state,modified=false}:{state?:string;modified?:boolean}) {
  const status=modified?'not_checked':state||'not_checked';
  const label=modified?'配置已修改，保存后重新检查':({
    passed:'连接检查通过',failed:'连接检查未通过',running:'连接检查进行中',
    interrupted:'上次检查已中断',not_checked:'配置已保存，尚未检查连接',
  } as Record<string,string>)[status]||'配置已保存，尚未检查连接';
  return <span className="model-connection-status" data-state={status} role="status">
    <span className="connection-status-indicator" aria-hidden="true"/>{label}
  </span>;
}
