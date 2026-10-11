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
                 closedAt: c.closedAt || '', module: f['Module'] || '', status: c.state === 'CLOSED' ? 'Done' : (f['Status'] || ''), priority: f['Priority'] || '',
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

  // Calc: aggregate tables, side by side so their sizes never interfere
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

  const owners = Array.from(new Set(m1.map(r => r.owner))).sort();
  const ownerRows = owners.map(o => [o].concat(BUCKETS.map(b => m1.filter(r => r.owner === o && bucketOf_(r.status) === b).length)));
  calc.getRange(1, 12, 1, 6).setValues([['Người làm'].concat(BUCKETS)]);
  if (ownerRows.length) calc.getRange(2, 12, ownerRows.length, 6).setValues(ownerRows);

  calc.getRange(1, 19, 1, 2).setValues([['Trạng thái', 'Số ticket']]);
  calc.getRange(2, 19, BUCKETS.length, 2).setValues(BUCKETS.map(b => [b, m1.filter(r => bucketOf_(r.status) === b).length]));

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
  const done = m1.filter(r => r.status === 'Done').length;
  const inprog = m1.filter(r => r.status === 'In Progress' || r.status === 'Review').length;
  const kpis = [
    ['MODULE', modules.length, '#1F3864'], ['TICKET M1', m1.length, '#1F3864'], ['ĐÃ XONG', done, '#2E7D32'],
    ['ĐANG LÀM / REVIEW', inprog, '#EF6C00'], ['% M1 XONG', m1.length ? done / m1.length : 0, '#2E7D32'],
    ['% NHÓM A XONG', cutA.length ? cutA.filter(r => r.status === 'Done').length / cutA.length : 0, '#2E7D32'],
    ['CHƯA GIAO NGƯỜI', m1.filter(r => r.owner === '(chưa giao)').length, '#C62828'],
    ['NGÀY CÒN LẠI', Math.max(0, Math.ceil((DEADLINE - new Date()) / 86400000)), '#6A1B9A']];
  buildDashboard_(kpis, modRows.length, ownerRows.length);
  writeModules_(rows);
  writeLinks_();
  styleSheets_();
  return rows.length;
}

// ───────────────────────── dashboard ─────────────────────────
const NAVY = '#1F3864', INK = '#263238', MUTED = '#78909C', BG = '#F5F7FA';
const COLORS = ['#CFD8DC', '#90CAF9', '#FFB74D', '#BA68C8', '#66BB6A'];
const FONT = 'Arial';

function chartStyle_(b, title) {
  return b.setHiddenDimensionStrategy(Charts.ChartHiddenDimensionStrategy.SHOW_BOTH) // data lives in the hidden Calc sheet
    .setOption('title', title)
    .setOption('titleTextStyle', {color: INK, fontSize: 14, bold: true, fontName: FONT})
    .setOption('fontName', FONT).setOption('backgroundColor', {fill: '#FFFFFF', stroke: '#E0E6ED', strokeWidth: 1})
    .setOption('legend', {position: 'top', textStyle: {color: INK, fontSize: 11}})
    .setOption('hAxis', {textStyle: {color: MUTED, fontSize: 10}, gridlines: {color: '#EEF1F5'}})
    .setOption('vAxis', {textStyle: {color: INK, fontSize: 11}, gridlines: {color: '#EEF1F5'}});
}

function buildDashboard_(kpis, nMod, nOwn) {
  const ss = SpreadsheetApp.getActive();
  const dash = sheet_('Dashboard'), calc = sheet_('Calc'), hist = sheet_('History');
  dash.getCharts().forEach(c => dash.removeChart(c));
  dash.getRange(1, 1, dash.getMaxRows(), dash.getMaxColumns()).breakApart();
  dash.clear(); dash.clearConditionalFormatRules();
  dash.setHiddenGridlines(true);
  const ncol = 17;
  dash.getRange(1, 1, 120, ncol).setBackground(BG).setFontFamily(FONT);
  for (let c = 1; c <= ncol; c++) dash.setColumnWidth(c, 92);
  dash.setColumnWidth(1, 16);

  // Banner
  dash.setRowHeight(1, 12);
  dash.getRange(2, 2, 1, ncol - 1).merge().setValue('TreasuryPilot · Bảng theo dõi tiến độ')
    .setBackground(NAVY).setFontColor('#FFFFFF').setFontSize(20).setFontWeight('bold').setVerticalAlignment('middle');
  dash.setRowHeight(2, 46);
  const updated = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'HH:mm dd/MM/yyyy');
  dash.getRange(3, 2, 1, ncol - 1).merge()
    .setValue('FinTechathon 2026 · Hạn nộp 20/10/2026 23:59 (giờ Bắc Kinh) · Tự cập nhật mỗi giờ từ GitHub Project · Lần cuối: ' + updated)
    .setBackground(NAVY).setFontColor('#CFD8DC').setFontSize(10);
  dash.setRowHeight(3, 24); dash.setRowHeight(4, 14);

  // KPI cards: 8 cards, 2 columns wide each, starting at column B
  kpis.forEach((k, i) => {
    const col = 2 + i * 2;
    const label = dash.getRange(5, col, 1, 2).merge(), value = dash.getRange(6, col, 1, 2).merge();
    label.setValue(k[0]).setFontSize(9).setFontColor(MUTED).setFontWeight('bold').setHorizontalAlignment('center')
      .setBackground('#FFFFFF').setBorder(true, true, false, true, false, false, '#E0E6ED', SpreadsheetApp.BorderStyle.SOLID);
    value.setValue(k[1]).setFontSize(26).setFontWeight('bold').setFontColor(k[2]).setHorizontalAlignment('center')
      .setVerticalAlignment('middle').setBackground('#FFFFFF')
      .setBorder(false, true, true, true, false, false, '#E0E6ED', SpreadsheetApp.BorderStyle.SOLID);
    if (typeof k[1] === 'number' && k[1] <= 1 && k[0].indexOf('%') === 0) value.setNumberFormat('0%');
  });
  dash.setRowHeight(5, 26); dash.setRowHeight(6, 54); dash.setRowHeight(7, 16);

  // Section helper
  const section = (row, text) => dash.getRange(row, 2, 1, ncol - 1).merge().setValue(text)
    .setFontSize(12).setFontWeight('bold').setFontColor(NAVY)
    .setBorder(false, false, true, false, false, false, NAVY, SpreadsheetApp.BorderStyle.SOLID_MEDIUM);

  section(8, 'Tiến độ theo module');
  const modRange = calc.getRange(1, 1, nMod + 1, 6);
  dash.insertChart(chartStyle_(dash.newChart().asBarChart().setStacked().addRange(modRange).setNumHeaders(1), 'Số ticket M1 theo trạng thái')
    .setOption('colors', COLORS).setOption('height', 560).setOption('width', 760)
    .setPosition(9, 2, 4, 6).build());
  dash.insertChart(chartStyle_(dash.newChart().asBarChart()
      .addRange(calc.getRange(1, 1, nMod + 1, 1)).addRange(calc.getRange(1, 8, nMod + 1, 1)).setNumHeaders(1), '% hoàn thành (theo số ticket)')
    .setOption('colors', ['#43A047']).setOption('legend', {position: 'none'})
    .setOption('hAxis', {format: 'percent', viewWindow: {min: 0, max: 1}, textStyle: {color: MUTED}, gridlines: {color: '#EEF1F5'}})
    .setOption('height', 560).setOption('width', 600)
    .setPosition(9, 10, 20, 6).build());

  section(40, 'Con người & trạng thái');
  if (nOwn > 0) dash.insertChart(chartStyle_(dash.newChart().asColumnChart().setStacked()
      .addRange(calc.getRange(1, 12, nOwn + 1, 6)).setNumHeaders(1), 'Ai đang làm gì (số ticket M1)')
    .setOption('colors', COLORS).setOption('height', 400).setOption('width', 760)
    .setPosition(41, 2, 4, 6).build());
  dash.insertChart(chartStyle_(dash.newChart().asPieChart()
      .addRange(calc.getRange(1, 19, BUCKETS.length + 1, 2)).setNumHeaders(1), 'Tổng quan trạng thái M1')
    .setOption('pieHole', 0.55).setOption('colors', COLORS).setOption('pieSliceTextStyle', {color: INK})
    .setOption('legend', {position: 'right', textStyle: {color: INK, fontSize: 11}})
    .setOption('height', 400).setOption('width', 600).setPosition(41, 10, 20, 6).build());

  section(62, 'Burn-up nhóm A (bắt buộc cho bản nộp)');
  dash.insertChart(chartStyle_(dash.newChart().asAreaChart()
      .addRange(hist.getRange(1, 1, Math.max(hist.getLastRow(), 2), 3)).setNumHeaders(1), 'Tổng ticket nhóm A và số đã xong theo ngày')
    .setOption('colors', ['#B0BEC5', '#2E7D32']).setOption('areaOpacity', 0.15).setOption('lineWidth', 3).setOption('pointSize', 5)
    .setOption('height', 340).setOption('width', 1380).setPosition(63, 2, 4, 6).build());

  // Module table
  const tRow = 82;
  section(tRow, 'Bảng module · ai đang làm');
  const head = ['Module', 'Chưa bắt đầu', 'Đã giao', 'Đang làm', 'Review', 'Xong', 'Tổng', '% xong', '% công', 'Người làm'];
  const vals = calc.getRange(2, 1, nMod, 10).getValues();
  dash.getRange(tRow + 1, 2, 1, 10).setValues([head]).setBackground(NAVY).setFontColor('#FFFFFF').setFontWeight('bold')
    .setHorizontalAlignment('center');
  if (nMod) {
    const body = dash.getRange(tRow + 2, 2, nMod, 10);
    body.setValues(vals).setBackground('#FFFFFF').setFontColor(INK).setFontSize(10)
      .setBorder(true, true, true, true, true, true, '#E0E6ED', SpreadsheetApp.BorderStyle.SOLID);
    dash.getRange(tRow + 2, 3, nMod, 7).setHorizontalAlignment('center');
    dash.getRange(tRow + 2, 3, nMod, 6).setNumberFormat('0');
    dash.getRange(tRow + 2, 9, nMod, 2).setNumberFormat('0%');
    for (let i = 0; i < nMod; i += 2) dash.getRange(tRow + 2 + i, 2, 1, 10).setBackground('#F8FAFC');
    const pct = dash.getRange(tRow + 2, 9, nMod, 1);
    dash.setConditionalFormatRules([SpreadsheetApp.newConditionalFormatRule().setGradientMinpointWithValue('#FFFFFF', SpreadsheetApp.InterpolationType.NUMBER, '0')
      .setGradientMaxpointWithValue('#81C784', SpreadsheetApp.InterpolationType.NUMBER, '1').setRanges([pct]).build()]);
  }
  // "Người làm" spans K:Q so the KPI cards keep equal widths
  for (let r = tRow + 1; r <= tRow + 1 + nMod; r++) dash.getRange(r, 11, 1, 7).merge().setWrap(true);
  dash.getRange(tRow + 1, 11, 1, 7).setBackground(NAVY);
  dash.setFrozenRows(0);
  ss.setActiveSheet(dash); ss.moveActiveSheet(1);
}

// ───────────────────────── other sheets ─────────────────────────
function header_(sh, n) {
  sh.getRange(1, 1, 1, n).setBackground(NAVY).setFontColor('#FFFFFF').setFontWeight('bold').setFontFamily(FONT)
    .setVerticalAlignment('middle').setWrap(true);
  sh.setRowHeight(1, 32); sh.setFrozenRows(1);
}
function band_(sh, rows, cols) {
  sh.getBandings().forEach(b => b.remove());
  if (rows > 1) sh.getRange(1, 1, rows, cols).applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false)
    .setHeaderRowColor(NAVY);
}

function styleSheets_() {
  const ss = SpreadsheetApp.getActive();
  // Data
  const data = sheet_('Data');
  const n = data.getLastRow(), c = data.getLastColumn();
  data.getRange(1, 1, n, c).setFontFamily(FONT).setFontSize(10).setVerticalAlignment('middle');
  band_(data, n, c); header_(data, c);
  [90, 55, 380, 120, 140, 110, 130, 70, 60, 50, 70, 120, 100, 60].forEach((w, i) => data.setColumnWidth(i + 1, w));
  if (n > 1) {
    const links = data.getRange(2, 14, n - 1, 1).getValues().map(r => [r[0]
      ? SpreadsheetApp.newRichTextValue().setText('Mở ↗').setLinkUrl(String(r[0])).build()
      : SpreadsheetApp.newRichTextValue().setText('').build()]);
    data.getRange(2, 14, n - 1, 1).setRichTextValues(links);
    const st = data.getRange(2, 6, n - 1, 1);
    const rule = (txt, bg, fg) => SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(txt).setBackground(bg).setFontColor(fg).setRanges([st]).build();
    data.setConditionalFormatRules([rule('Xong', '#C8E6C9', '#1B5E20'), rule('Review', '#E1BEE7', '#4A148C'),
      rule('Đang làm', '#FFE0B2', '#E65100'), rule('Đã giao', '#BBDEFB', '#0D47A1'), rule('Chưa bắt đầu', '#ECEFF1', '#455A64')]);
  }
  data.setTabColor('#1E88E5');
  // History
  const hist = sheet_('History');
  header_(hist, 5); hist.getRange(2, 1, Math.max(hist.getLastRow() - 1, 1), 1).setNumberFormat('dd/MM/yyyy');
  hist.getRange(1, 1, hist.getLastRow(), 5).setFontFamily(FONT).setHorizontalAlignment('center');
  [110, 100, 100, 100, 100].forEach((w, i) => hist.setColumnWidth(i + 1, w));
  hist.setTabColor('#8E24AA');
  // Links (static sheet created by hand)
  const links = ss.getSheetByName('Links');
  if (links && links.getLastRow() > 1) {
    const ln = links.getLastRow(), lc = links.getLastColumn();
    links.getRange(1, 1, ln, lc).setFontFamily(FONT).setFontSize(10).setVerticalAlignment('middle').setWrap(true);
    band_(links, ln, lc); header_(links, lc);
    [160, 240, 420, 90, 110].forEach((w, i) => links.setColumnWidth(i + 1, w));
    links.getRange(2, 4, ln - 1, 1).setWrap(false);
    links.setTabColor('#43A047');
  }
  // Calc is internal
  const calc = sheet_('Calc'); calc.hideSheet(); calc.setTabColor('#9E9E9E');
  sheet_('Dashboard').setTabColor(NAVY);
  // Order: Dashboard, Links, Data, History
  ['Dashboard', 'Modules', 'Links', 'Data', 'History'].forEach((name, i) => {
    const sh = ss.getSheetByName(name); if (sh) { ss.setActiveSheet(sh); ss.moveActiveSheet(i + 1); }
  });
  ss.setActiveSheet(sheet_('Dashboard'));
}

// ───────────────────────── modules & links (docs ↔ tracker) ─────────────────────────
const DOC_URL = 'https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=';
const REPO_URL = 'https://github.com/Nostidus4/TreasuryPilot';
// [module id, name, GitHub folder (= Project "Module" value), Doc tab id, epic issue, owner, reviewer]
const MODULE_INFO = [
  ['M01', 'Định danh & phân quyền', 'identity', 't.xvsvolwbxoe4', 5, 'Nostidus4', 'therealtunguyen'],
  ['M02', 'Treasury & cấu hình chain', 'treasury', 't.ua49v9d729ex', 6, 'Nostidus4', 'therealtunguyen'],
  ['M03', 'Mandate, payee, ngoại lệ, pause', 'mandate', 't.hav7u6wrnhrh', 7, 'Nostidus4', 'therealtunguyen'],
  ['M04', 'Smart contract', 'contracts', 't.ftwmn7qgsviu', 2, 'longhuynh55', 'Nostidus4'],
  ['M05', 'Hóa đơn & duyệt', 'invoices', 't.c7pc1vyism9q', 8, 'Nostidus4', 'therealtunguyen'],
  ['M06', 'Đọc chain & theo dõi giao dịch', 'chain-reader', 't.5xkekgtj7ytn', 9, 'therealtunguyen', 'Nostidus4'],
  ['M07', 'Financial engine', 'financial-engine', 't.opopowdic7om', 3, 'Nostidus4', 'therealtunguyen'],
  ['M08', 'Policy engine & attestation', 'policy-engine', 't.e2tn8zn3rh1x', 4, 'therealtunguyen', 'Nostidus4'],
  ['M09', 'AI agent', 'agent', 't.8n0pk86vmqj', 10, 'therealtunguyen', 'Nostidus4'],
  ['M10', 'Điều phối & thực thi', 'execution', 't.z3pu3y89rrpf', 11, 'therealtunguyen', 'Nostidus4'],
  ['M11', 'Xác minh & đối soát', 'reconciliation', 't.aq3og043wqwg', 12, 'Nostidus4', 'therealtunguyen'],
  ['M12', 'Phục hồi & review', 'recovery', 't.wfmr5rsre8bk', 13, 'Nostidus4', 'therealtunguyen'],
  ['M13', 'Thông báo', 'notifications', 't.aqf8wklx9g54', 14, 'Nostidus4', 'therealtunguyen'],
  ['M14', 'Tuân thủ', 'compliance', 't.t2qyasr83441', 15, 'Nostidus4', 'therealtunguyen'],
  ['M15', 'Audit & bằng chứng', 'audit', 't.7fguvztm9hd7', 16, 'Nostidus4', 'therealtunguyen'],
  ['M16', 'Ứng dụng web', 'web', 't.l1smw0b1gvu7', 17, 'Nostidus4', 'therealtunguyen'],
  ['M17', 'Giám sát & phân tích', 'observability', 't.7jzr8rwztvxq', 18, 'therealtunguyen', 'Nostidus4'],
  ['M18', 'Quản trị nền tảng (Later)', 'admin', 't.td5yq8eho4o0', 19, '(Later)', ''],
  ['M19', 'DevEx & chất lượng', 'devex', 't.b0ie0gmovi43', 1, 'therealtunguyen', 'Nostidus4'],
  ['M20', 'Nghiệp vụ & bằng chứng', 'domain-evidence', 't.llpqfkgddaqt', 20, '(chia sau)', ''],
];
function link_(text, url) { return SpreadsheetApp.newRichTextValue().setText(text).setLinkUrl(url).build(); }

function writeModules_(rows) {
  const sh = sheet_('Modules');
  sh.clear(); sh.getBandings().forEach(b => b.remove());
  const head = ['ID', 'Module', 'Người làm', 'Review mặc định', 'Ticket M1', 'Xong', '% xong', 'Đang làm', 'Spec tiếng Việt', 'Spec GitHub', 'Epic'];
  sh.getRange(1, 1, 1, head.length).setValues([head]);
  const m1 = rows.filter(r => r.phase === 'M1');
  MODULE_INFO.forEach((m, i) => {
    const t = m1.filter(r => r.module === m[2]);
    const done = t.filter(r => r.status === 'Done').length;
    const doing = t.filter(r => r.status === 'In Progress' || r.status === 'Review').length;
    const r = i + 2;
    sh.getRange(r, 1, 1, 8).setValues([[m[0], m[1], m[5], m[6], t.length, done, t.length ? done / t.length : 0, doing]]);
    sh.getRange(r, 9).setRichTextValue(link_('Mở tab ↗', DOC_URL + m[3]));
    sh.getRange(r, 10).setRichTextValue(link_('README ↗', REPO_URL + '/blob/main/docs/modules/' + m[2] + '/README.md'));
    sh.getRange(r, 11).setRichTextValue(link_('#' + m[4] + ' ↗', REPO_URL + '/issues/' + m[4]));
  });
  const n = MODULE_INFO.length + 1;
  sh.getRange(2, 7, n - 1, 1).setNumberFormat('0%');
  sh.getRange(1, 1, n, head.length).setFontFamily(FONT).setFontSize(10).setVerticalAlignment('middle');
  band_(sh, n, head.length); header_(sh, head.length);
  [50, 250, 130, 130, 80, 60, 70, 80, 120, 110, 80].forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.setTabColor('#FB8C00');
}

function writeLinks_() {
  const sh = sheet_('Links');
  sh.clear(); sh.getBandings().forEach(b => b.remove());
  const tab = id => DOC_URL + id, gh = p => REPO_URL + p;
  const L = [
    ['Bắt đầu ở đây', 'Hướng dẫn phân công', 'Ai làm mảng nào, ai review, ticket làm được ngay', tab('t.3xlngx2j9mze'), 'Cả team'],
    ['Bắt đầu ở đây', 'Cập nhật v0.3 (Aave)', 'Thay đổi mới nhất: Aave supply/withdraw, bản duyệt hai mức tiền, D1–D10', tab('t.85x0bmmbqru0'), 'Cả team'],
    ['Bắt đầu ở đây', 'GitHub Project (bảng việc)', 'Mọi ticket, trạng thái, người làm', 'https://github.com/users/Nostidus4/projects/1', 'Cả team'],
    ['Bắt đầu ở đây', 'Repo GitHub', 'Code và tài liệu nguồn (tiếng Anh)', gh(''), 'Dev'],
    ['Tổng quan sản phẩm', '1. Tổng quan', 'Sản phẩm là gì, cho ai, giải quyết gì', tab('t.0'), 'Cả team'],
    ['Tổng quan sản phẩm', '2. Feature', 'Danh sách tính năng (M1 và Later)', tab('t.ew50tcmkirvg'), 'Cả team'],
    ['Tổng quan sản phẩm', '3. Business Rules', 'Luật nghiệp vụ (BR)', tab('t.ffh09bp2pqht'), 'Cả team'],
    ['Tổng quan sản phẩm', '4. Yêu cầu chức năng', 'FR', tab('t.clsimvrovdu'), 'Dev'],
    ['Tổng quan sản phẩm', '5. Yêu cầu phi chức năng', 'NFR', tab('t.mnv5tgkjdl2m'), 'Dev'],
    ['Quyết định', '6. Câu hỏi mở', 'Câu hỏi và kết quả', tab('t.kvfafawgpqlo'), 'Cả team'],
    ['Quyết định', '7. Nhật ký quyết định', 'Mọi quyết định đã chốt, theo thời gian', tab('t.64yp8l3vrd3f'), 'Cả team'],
    ['Quyết định', '9. Tech stack & ADR', 'Công nghệ và 19 quyết định kiến trúc', tab('t.p7m2nwkzrtsy'), 'Dev'],
    ['Kiến trúc', '8. Kiến trúc hệ thống', 'Thành phần, luồng, ranh giới tin cậy', tab('t.qqng6h47nr7k'), 'Dev'],
    ['Kiến trúc', '10. Module', 'Danh sách 20 module và tab spec của từng module', tab('t.k9zxyhbnvbxw'), 'Cả team'],
    ['Kiến trúc', '11. Data model', 'Bảng dữ liệu', tab('t.py8ti27c4ma4'), 'Dev'],
    ['Kiến trúc', '12. API', 'Endpoint và mã lỗi', tab('t.h95c4p9ohu6i'), 'Dev'],
    ['Kiến trúc', '13. Kiến trúc AI', 'AI được làm gì, không được làm gì', tab('t.yed8bvlknow6'), 'Dev'],
    ['Kiến trúc', '14. Cấu trúc repo', 'Thư mục và quy ước', tab('t.myx3296bhurc'), 'Dev'],
    ['Kế hoạch', '15. Backlog & phụ thuộc', 'Toàn bộ ticket, đợt thực hiện, chuỗi phụ thuộc', tab('t.79j5euuyx0pj'), 'Cả team'],
    ['Kế hoạch', 'Spec từng module', 'Xem sheet "Modules" (link tab tiếng Việt, README, epic)', '', 'Cả team'],
    ['Kế hoạch', 'Hạn mức cắt cho bản nộp', 'Tier A / B và ước tính công', gh('/blob/main/planning/SUBMISSION_CUT.md'), 'Trưởng nhóm'],
    ['Kế hoạch', 'Bản đồ phụ thuộc', 'Đợt thực hiện, chuỗi dài nhất', gh('/blob/main/planning/DEPENDENCIES.md'), 'Dev'],
    ['Nguồn', 'Spec v0.3 của nhóm trưởng', 'Bản gốc đã gộp vào docs (ADR-019)', gh('/blob/main/docs/source/TreasuryPilot-v0.3-team-lead-spec.md'), 'Cả team'],
    ['Nguồn', 'ADR-019', 'Quyết định gộp v0.3', gh('/blob/main/docs/adr/ADR-019-aave-liquidity-and-payment-options.md'), 'Dev'],
    ['Công cụ', 'Excel tracker', 'Bản Excel của bảng việc (tạo từ GitHub)', gh('/blob/main/planning/tracker/TreasuryPilot-Tracker.xlsx'), 'Trưởng nhóm'],
  ];
  const head = ['Nhóm', 'Tên', 'Nội dung', 'Link', 'Ai dùng'];
  sh.getRange(1, 1, 1, 5).setValues([head]);
  sh.getRange(2, 1, L.length, 5).setValues(L.map(r => [r[0], r[1], r[2], '', r[4]]));
  L.forEach((r, i) => { if (r[3]) sh.getRange(i + 2, 4).setRichTextValue(link_('Mở ↗', r[3])); });
}
