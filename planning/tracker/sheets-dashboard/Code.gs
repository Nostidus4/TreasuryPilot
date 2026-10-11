/**
 * TreasuryPilot progress dashboard for Google Sheets.
 * Pulls the GitHub Project "TreasuryPilot · Delivery" (users/Nostidus4/projects/1)
 * and draws charts: progress per module, workload per person, overall status, Cut A burn-up.
 *
 * Install: Extensions → Apps Script → paste this file → Save → run `setup` once.
 * `setup` asks for a GitHub classic token (scopes: repo, read:project), stores it in
 * Script Properties (never in the sheet), builds the sheets and charts, and adds an hourly trigger.
 *
 * GitHub stays the source of truth. Do not edit the "Data" sheet by hand; it is overwritten.
 */
const GH_OWNER = 'Nostidus4';
const GH_PROJECT_NUMBER = 1;
const DEADLINE = new Date('2026-10-20T15:59:00Z'); // 23:59 Beijing time
const STATUS_ORDER = ['Draft', 'Needs Discussion', 'Ready for Review', 'Accepted', 'Ready for Assignment',
                      'Assigned', 'In Progress', 'Review', 'Done'];
// Grouped statuses used in charts
const BUCKETS = ['Chưa bắt đầu', 'Đã giao', 'Đang làm', 'Review', 'Xong'];
function bucketOf_(status) {
  if (status === 'Done') return 'Xong';
  if (status === 'Review') return 'Review';
  if (status === 'In Progress') return 'Đang làm';
  if (status === 'Assigned') return 'Đã giao';
  return 'Chưa bắt đầu';
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('TreasuryPilot')
    .addItem('Cập nhật ngay', 'refresh')
    .addItem('Cài đặt / đổi token', 'setup')
    .addToUi();
}

function setup() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('GITHUB_TOKEN') ||
      ui.alert('Đổi GitHub token?', ui.ButtonSet.YES_NO) === ui.Button.YES) {
    const r = ui.prompt('GitHub token', 'Dán GitHub classic token (scopes: repo, read:project). Token chỉ lưu trong Script Properties, không lưu trong sheet.', ui.ButtonSet.OK_CANCEL);
    if (r.getSelectedButton() !== ui.Button.OK || !r.getResponseText().trim()) return;
    props.setProperty('GITHUB_TOKEN', r.getResponseText().trim());
  }
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('refresh').timeBased().everyHours(1).create();
  refresh();
  ui.alert('Xong. Dashboard tự cập nhật mỗi giờ. Menu TreasuryPilot → Cập nhật ngay để làm mới thủ công.');
}

// ───────────────────────── data ─────────────────────────
function fetchItems_() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Chưa có GitHub token. Chạy menu TreasuryPilot → Cài đặt.');
  const query = `query($login:String!,$num:Int!,$after:String){user(login:$login){projectV2(number:$num){
    items(first:100,after:$after){pageInfo{hasNextPage endCursor}
      nodes{fieldValues(first:20){nodes{
        ...on ProjectV2ItemFieldSingleSelectValue{name field{...on ProjectV2FieldCommon{name}}}
        ...on ProjectV2ItemFieldTextValue{text field{...on ProjectV2FieldCommon{name}}}}}
       content{...on Issue{number title url state closedAt assignees(first:5){nodes{login}}}}}}}}}`;
  let after = null, rows = [];
  do {
    const res = UrlFetchApp.fetch('https://api.github.com/graphql', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: {Authorization: 'bearer ' + token},
      payload: JSON.stringify({query, variables: {login: GH_OWNER, num: GH_PROJECT_NUMBER, after}})
    });
    const body = JSON.parse(res.getContentText());
    if (body.errors || res.getResponseCode() !== 200) throw new Error(res.getContentText().slice(0, 500));
    const items = body.data.user.projectV2.items;
    items.nodes.forEach(n => {
      const f = {};
      n.fieldValues.nodes.forEach(v => { if (v && v.field) f[v.field.name] = v.name !== undefined ? v.name : v.text; });
      const c = n.content || {};
      const assignees = ((c.assignees || {}).nodes || []).map(a => a.login).join(', ');
      rows.push({id: f['Ticket ID'] || '', gh: c.number, title: c.title || '', url: c.url || '', state: c.state || '',
                 closedAt: c.closedAt || '', module: f['Module'] || '', status: f['Status'] || '', priority: f['Priority'] || '',
                 phase: f['Phase'] || '', size: f['Size'] || '', cut: f['Cut'] || '', area: f['Area'] || '',
                 owner: f['Owner'] || assignees || '(chưa giao)', assignees});
    });
    after = items.pageInfo.hasNextPage ? items.pageInfo.endCursor : null;
  } while (after);
  return rows.filter(r => r.id && r.id.indexOf('EPIC-') !== 0);
}

function sheet_(name) {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function refresh() {
  const rows = fetchItems_();
  const days = {S: 0.5, M: 1, L: 2};
  // Data
  const data = sheet_('Data');
  data.clear();
  const head = ['Ticket ID', 'GH #', 'Title', 'Module', 'Status', 'Nhóm trạng thái', 'Người làm', 'Priority', 'Phase', 'Size',
                'Est. days', 'Cut', 'Area', 'Link'];
  const vals = rows.sort((a, b) => a.id < b.id ? -1 : 1).map(r => [r.id, r.gh, r.title, r.module, r.status, bucketOf_(r.status),
    r.owner, r.priority, r.phase, r.size, days[r.size] || 0, r.cut, r.area, r.url]);
  data.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
  if (vals.length) data.getRange(2, 1, vals.length, head.length).setValues(vals);
  data.setFrozenRows(1);

  // Calc: aggregate tables that the charts read
  const calc = sheet_('Calc');
  calc.clear();
  const m1 = rows.filter(r => r.phase === 'M1');
  const modules = Array.from(new Set(m1.map(r => r.module))).sort();
  const modRows = modules.map(mod => {
    const t = m1.filter(r => r.module === mod);
    const counts = BUCKETS.map(b => t.filter(r => bucketOf_(r.status) === b).length);
    const done = counts[4], total = t.length;
    const effort = t.reduce((s, r) => s + (days[r.size] || 0), 0);
    const effortDone = t.filter(r => r.status === 'Done').reduce((s, r) => s + (days[r.size] || 0), 0);
    const people = Array.from(new Set(t.map(r => r.owner).filter(o => o !== '(chưa giao)'))).join(', ') || '(chưa giao)';
    return [mod].concat(counts).concat([total, total ? done / total : 0, effort ? effortDone / effort : 0, people]);
  });
  calc.getRange(1, 1, 1, 10).setValues([['Module'].concat(BUCKETS).concat(['Tổng', '% xong (ticket)', '% xong (công)', 'Người làm'])]);
  if (modRows.length) calc.getRange(2, 1, modRows.length, 10).setValues(modRows);
  calc.getRange(2, 8, Math.max(modRows.length, 1), 2).setNumberFormat('0%');

  const owners = Array.from(new Set(m1.map(r => r.owner))).sort();
  const ownerRows = owners.map(o => [o].concat(BUCKETS.map(b => m1.filter(r => r.owner === o && bucketOf_(r.status) === b).length)));
  const oStart = modRows.length + 4;
  calc.getRange(oStart, 1, 1, 6).setValues([['Người làm'].concat(BUCKETS)]);
  if (ownerRows.length) calc.getRange(oStart + 1, 1, ownerRows.length, 6).setValues(ownerRows);

  const sStart = oStart + ownerRows.length + 3;
  calc.getRange(sStart, 1, 1, 2).setValues([['Trạng thái', 'Số ticket (M1)']]);
  calc.getRange(sStart + 1, 1, BUCKETS.length, 2).setValues(BUCKETS.map(b => [b, m1.filter(r => bucketOf_(r.status) === b).length]));

  // History (one row per day) for the burn-up chart
  const hist = sheet_('History');
  if (hist.getLastRow() === 0) hist.appendRow(['Ngày', 'Cut A tổng', 'Cut A xong', 'M1 tổng', 'M1 xong']);
  const today = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'yyyy-MM-dd');
  const cutA = m1.filter(r => r.cut === 'A');
  const line = [today, cutA.length, cutA.filter(r => r.status === 'Done').length, m1.length, m1.filter(r => r.status === 'Done').length];
  const last = hist.getLastRow();
  const lastVal = last > 1 ? hist.getRange(last, 1).getValue() : '';
  const lastDay = lastVal instanceof Date ? Utilities.formatDate(lastVal, 'Asia/Ho_Chi_Minh', 'yyyy-MM-dd') : String(lastVal);
  if (last > 1 && lastDay === today) hist.getRange(last, 1, 1, 5).setValues([line]);
  else hist.appendRow(line);

  // Dashboard KPIs
  const dash = sheet_('Dashboard');
  const done = m1.filter(r => r.status === 'Done').length;
  const inprog = m1.filter(r => r.status === 'In Progress' || r.status === 'Review').length;
  const kpis = [
    ['Số module', modules.length], ['Ticket M1', m1.length], ['Đã xong', done], ['Đang làm / review', inprog],
    ['% M1 xong', m1.length ? done / m1.length : 0],
    ['% Cut A xong', cutA.length ? cutA.filter(r => r.status === 'Done').length / cutA.length : 0],
    ['Chưa giao người', m1.filter(r => r.owner === '(chưa giao)').length],
    ['Còn lại tới hạn nộp (ngày)', Math.max(0, Math.ceil((DEADLINE - new Date()) / 86400000))],
    ['Cập nhật lúc', Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'yyyy-MM-dd HH:mm')]];
  dash.getRange('A1').setValue('TreasuryPilot · Tiến độ').setFontSize(16).setFontWeight('bold');
  dash.getRange(3, 1, 1, kpis.length).setValues([kpis.map(k => k[0])]).setFontWeight('bold').setBackground('#1F3864').setFontColor('white').setWrap(true);
  dash.getRange(4, 1, 1, kpis.length).setValues([kpis.map(k => k[1])]).setFontSize(14).setHorizontalAlignment('center');
  dash.getRange(4, 5, 1, 2).setNumberFormat('0%');
  buildCharts_(); // rebuilt every refresh so ranges follow new people/modules
  return rows.length;
}

// ───────────────────────── charts ─────────────────────────
function buildCharts_() {
  const ss = SpreadsheetApp.getActive();
  const dash = sheet_('Dashboard'), calc = sheet_('Calc'), hist = sheet_('History');
  dash.getCharts().forEach(c => dash.removeChart(c));
  const nMod = calc.getRange('A2:A').getValues().filter(r => r[0] !== '').length;
  const oStart = nMod + 4;
  let nOwn = 0; while (calc.getRange(oStart + 1 + nOwn, 1).getValue() !== '') nOwn++;
  const sStart = oStart + nOwn + 3;
  const colors = ['#BDBDBD', '#90CAF9', '#FFB74D', '#BA68C8', '#66BB6A'];

  // 1. Progress per module (stacked bars)
  dash.insertChart(dash.newChart().asBarChart().setStacked()
    .addRange(calc.getRange(1, 1, nMod + 1, 6))
    .setOption('title', 'Tiến độ từng module (số ticket M1)').setOption('colors', colors)
    .setOption('legend', {position: 'top'}).setOption('height', 520).setOption('width', 760)
    .setPosition(6, 1, 0, 0).build());
  // 2. % done per module
  dash.insertChart(dash.newChart().asColumnChart()
    .addRange(calc.getRange(1, 1, nMod + 1, 1)).addRange(calc.getRange(1, 8, nMod + 1, 1))
    .setOption('title', '% hoàn thành theo module').setOption('vAxis', {format: 'percent', viewWindow: {min: 0, max: 1}})
    .setOption('legend', {position: 'none'}).setOption('colors', ['#66BB6A']).setOption('height', 520).setOption('width', 620)
    .setPosition(6, 9, 0, 0).build());
  // 3. Workload per person
  if (nOwn > 0) dash.insertChart(dash.newChart().asColumnChart().setStacked()
    .addRange(calc.getRange(oStart, 1, nOwn + 1, 6))
    .setOption('title', 'Ai đang làm gì (số ticket theo người)').setOption('colors', colors)
    .setOption('legend', {position: 'top'}).setOption('height', 420).setOption('width', 760)
    .setPosition(33, 1, 0, 0).build());
  // 4. Overall status
  dash.insertChart(dash.newChart().asPieChart()
    .addRange(calc.getRange(sStart, 1, BUCKETS.length + 1, 2))
    .setOption('title', 'Tổng quan trạng thái M1').setOption('pieHole', 0.4).setOption('colors', colors)
    .setOption('height', 420).setOption('width', 620).setPosition(33, 9, 0, 0).build());
  // 5. Cut A burn-up
  dash.insertChart(dash.newChart().asLineChart()
    .addRange(hist.getRange('A1:C'))
    .setOption('title', 'Burn-up nhóm A (bắt buộc cho bản nộp)').setOption('legend', {position: 'top'})
    .setOption('colors', ['#9E9E9E', '#2E7D32']).setOption('height', 380).setOption('width', 1380)
    .setPosition(55, 1, 0, 0).build());

  // Module table with people, under the charts
  const tStart = 76;
  dash.getRange(tStart, 1, 60, 10).clearContent().clearFormat();
  dash.getRange(tStart, 1).setValue('Bảng module · người làm').setFontWeight('bold').setFontSize(12);
  dash.getRange(tStart + 1, 1, nMod + 1, 10).setValues(calc.getRange(1, 1, nMod + 1, 10).getValues());
  dash.getRange(tStart + 1, 1, 1, 10).setFontWeight('bold').setBackground('#1F3864').setFontColor('white');
  dash.getRange(tStart + 2, 8, nMod, 2).setNumberFormat('0%');
  ss.setActiveSheet(dash); ss.moveActiveSheet(1);
}
