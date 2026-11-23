import {render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {HistoryProgress} from './HistoryProgress';
it('shows extraction, reduction and reuse independently of archive counts',()=>{
 render(<HistoryProgress counts={{analysis_chunks_total:5,analysis_chunks_completed:3,analysis_chunks_reused:2,analysis_merge_total:2,analysis_merge_completed:1,analysis_material_total:12,analysis_material_completed:7}} state="running"/>);
 expect(screen.getByText('分段提取 3 / 5 · 复用 2 段')).toBeVisible();
 expect(screen.getByText('事实归纳 1 / 2')).toBeVisible();
 expect(screen.getByText('已处理 7 / 12 条原文')).toBeVisible();
 expect(screen.getByRole('progressbar',{name:'长历史提取进度'})).toHaveAttribute('value','3');
});
it('failed history explains checkpoints without claiming a new profile was published',()=>{
 render(<HistoryProgress counts={{analysis_chunks_total:5,analysis_chunks_completed:3,analysis_chunks_failed:1}} state="failed"/>);
 expect(screen.getByText(/已校验的分段已保存/)).toBeVisible();
 expect(screen.getByRole('progressbar',{name:'长历史提取进度'})).toHaveAttribute('value','3');
});
it('keeps the direct small-history interface compact',()=>{
 const {container}=render(<HistoryProgress counts={{analysis_chunks_total:1,analysis_chunks_completed:1}} state="succeeded"/>);
 expect(container).toBeEmptyDOMElement();
});
it('shows a pending provider response with zero validated high-value messages',()=>{
 render(<HistoryProgress counts={{relevance_total:341,relevance_high:37,analysis_chunks_total:3,analysis_material_total:37,analysis_refinements:1,model_requests_started:2,model_requests:1}} state="running"/>);
 expect(screen.getByText('模型已请求 2 次 · 等待模型返回')).toBeVisible();
 expect(screen.getByRole('progressbar')).toHaveAttribute('max','37');
 expect(screen.getByRole('progressbar')).toHaveAttribute('value','0');
});
