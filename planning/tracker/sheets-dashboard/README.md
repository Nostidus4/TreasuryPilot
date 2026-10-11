# Google Sheets dashboard

`Code.gs` turns the team Google Sheet into a live progress dashboard fed by the GitHub Project.

## Charts
1. Progress per module (stacked: chưa bắt đầu / đã giao / đang làm / review / xong)
2. % done per module
3. Who is doing what (tickets per person, by status)
4. Overall M1 status (donut)
5. Burn-up for Cut A (one point per day, from the History sheet)

Plus KPI tiles: number of modules, M1 tickets, done, in progress, % done, % Cut A done, unassigned tickets, days to deadline, last update. Also a module table listing who works on each module.

## "Who" = Owner field, else GitHub assignees
The Project has a text field **Owner**. Use it for people without a GitHub account (for example the advisors). If Owner is empty, the dashboard uses the issue's GitHub assignees.

## Install (once)
1. Open the Sheet → Extensions (Tiện ích) → Apps Script, paste `Code.gs`, Save.
2. Create a GitHub **classic** token with scopes `repo` and `read:project` (github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)).
3. In the Sheet, reload, then menu **TreasuryPilot → Cài đặt / đổi token**, paste the token, and approve Google's authorization screen.
4. The script refreshes every hour. Use **TreasuryPilot → Cập nhật ngay** for an immediate refresh.

The token is stored only in Script Properties, never in a cell. Anyone with edit access to the Apps Script project can read Script Properties, so give the Sheet's edit rights only to the core team and share it **view-only** with others.
