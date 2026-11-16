export const routes=['实验档案','事件核对','身份归并','实验裁决','发布记录'];export function page(){return Math.min(4,Math.max(0,Number(location.hash.slice(1))||0))}
