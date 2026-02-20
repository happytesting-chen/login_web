# Staff Attendance System — PRD

## Overview

A mobile-friendly web app for staff clock-in/clock-out and leave management, accessible via a public ngrok URL. After login, users are redirected to a **dashboard** with grouped feature boxes. Admin/HR users have additional management capabilities.

---

## User Roles

| Role | Who | Permissions |
|------|-----|-------------|
| **Admin / HR** | Username contains "admin" or "shawn" (case-insensitive) | All staff attendance & OT records, leave management, entitlements, login not recorded in DB |
| **Staff** | Everyone else | Clock in/out, view own records, apply leave, view own leave balance |

---

## Features

### 1. Login Page
- Staff open the shared ngrok URL on their **phone** or laptop
- Enter username & password → click **Login**
- **Remember Me** checkbox saves credentials in `localStorage` for next visit
- "Not a user? **Register here**" link for one-time registration
- After login → redirected to **Dashboard**

### 2. Dashboard
After login, users see a dashboard with feature boxes organized into two groups:

**Attendance group:**

| Box | Description | Who |
|-----|-------------|-----|
| 🟢 Clock In | Start your day (captures geolocation) | Staff only |
| 🔴 Clock Out | End your day (captures geolocation) | Staff only |
| 📋 My Records | View own attendance & OT history with filters | Staff only |
| 🔑 All Attendance & OT | View all staff records (phone: cards, laptop: redirects to table page) | Admin only |

> **Note:** Clock In, Clock Out, and My Records are **hidden for admin** users since admin logins are not recorded in the database.

**Leave group:**

| Box | Description | Who |
|-----|-------------|-----|
| 📝 Apply Leave | Submit a leave request | All |
| 📊 Leave Balance | View own remaining leave days | All |
| ⚙️ Leave Management | Set staff entitlements & approve/reject requests | Admin only |
| 📑 All Leave Records | View all staff leave balances & history | Admin only |

### 3. Clock In / Clock Out
- Separate **Clock In** and **Clock Out** buttons
- Browser **geolocation** captured and reverse-geocoded to area/address
- IP address and user agent logged
- Late/OT badges calculated automatically
- Admin logins do **not** write to `login_events` (keeps records clean)

### 4. Attendance Records & Filters
- **My Records**: staff see own records as cards
- **All Attendance & OT** (admin): see all staff records
  - Phone (< 768px): card view on dashboard
  - Laptop (≥ 768px): redirects to `/admin/logins` table page
- **Filters available** (both card view and table view):
  - Username (admin only)
  - Date range (from / to)
  - OT filter (All / Has OT / No OT)
  - Event filter (All / Clock In / Clock Out)
- **∑ Sum OT** button: calculates total OT hours for all visible records, broken down per user
- **Clear Filters** button to reset all filters
- Column sorting on table view (click headers)

### 5. Leave Application
- Staff select leave type (Annual / Sick / Child Care), date range, and reason
- Shows **real-time balance** info while filling the form
- Weekdays only are counted (Mon–Fri)
- Validates against remaining balance before submission
- On submission:
  - Saved to database with status **Pending**
  - **Email notification** sent to boss (`cherrycc0324@gmail.com`) via Gmail SMTP
  - Email contains leave details + **Approve** / **Reject** buttons

### 6. Email-Based Leave Approval
- Boss receives email with staff name, leave type, dates, reason
- Email has clickable **✓ Approve** and **✗ Reject** buttons
- Clicking a button opens a web page that:
  - Updates the leave status in the database
  - Shows a confirmation page (approved/rejected)
- Links are **signed tokens** (secure, cannot be forged, expire after 7 days)
- If already decided, shows "Already Approved/Rejected" message
- Admin can also approve/reject from the **Leave Management** dashboard box

### 7. Leave Management (Admin)
- **Set entitlements**: configure how many leave days each staff gets per type
- **Approve/reject** pending leave requests from the dashboard
- Shows "**Successfully updated!**" after saving entitlements
- **All Leave Records** box: overview of every staff member's balance + recent leave history with status badges

### 8. Leave Balance
- Staff can view their own balance: total, used, pending, remaining per leave type
- Low balance (≤ 2 days) highlighted in red
- Admin can view any staff member's balance

---

## Business Rules

| Rule | Detail |
|------|--------|
| Work start | 8:30 AM (SGT) |
| Work end | 5:00 PM (SGT) |
| Late | Clock In after 8:30 AM |
| OT | Clock Out after 5:00 PM; OT minutes = actual − 5:00 PM |
| Working hours | Clock Out time − Clock In time |
| Leave types | Annual Leave, Sick Leave, Child Care Leave |
| Leave counting | Weekdays only (Mon–Fri) |
| Timezone | Singapore (UTC+8) |

---

## Email Configuration

| Setting | Environment Variable | Default |
|---------|---------------------|---------|
| Sender Gmail | `SMTP_EMAIL` | *(required)* |
| Gmail App Password | `SMTP_PASSWORD` | *(required)* |
| Boss email | `BOSS_EMAIL` | `cherrycc0324@gmail.com` |

Requires Gmail **2-Step Verification** + **App Password** (not regular password).

---

## Deployment

- Flask app runs on server machine (`python3 app.py`)
- **ngrok** exposes it publicly (`ngrok http 5000`)
- Share the ngrok URL with staff
- Both must run simultaneously in separate terminals
- Set `SMTP_EMAIL` and `SMTP_PASSWORD` env vars before starting the app
- Free plan: URL changes on each ngrok restart

---

## Tech Stack

- **Backend**: Python / Flask / SQLite
- **Frontend**: HTML dashboard, vanilla JS, mobile-responsive
- **Auth**: bcrypt password hashing, Flask sessions
- **Geocoding**: OpenStreetMap Nominatim (reverse geocode)
- **Email**: Gmail SMTP with `itsdangerous` signed tokens for approval links
- **Tunnel**: ngrok (free tier)
