import { useId, type SelectHTMLAttributes } from "react";
export function SelectField({label,options,id,...props}: SelectHTMLAttributes<HTMLSelectElement> & {label:string;options:{value:string;label:string}[]}) {
  const generated=useId();const fieldId=id||generated;
  return <div className="field"><label htmlFor={fieldId}>{label}</label><select {...props} id={fieldId} className="form-control">{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></div>;
}
