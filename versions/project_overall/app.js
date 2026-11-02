// 展开实测字段来源，便于开发人员快速核对协议。
const evidence = document.querySelector('#evidence');
document.querySelector('#toggle-evidence').addEventListener('click', () => {
  evidence.hidden = !evidence.hidden;
});
