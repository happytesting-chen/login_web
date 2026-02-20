Context

I have a Flask + SQLite login system with:

User authentication (username + password)

Login audit logging (login_events table)

An admin page that displays all login records in an HTML table

Currently, login records show:

location_source = none

No human-readable location (only IP / empty lat-lon)

Goal

When a user logs in, capture and display a human-readable Singapore location, such as:

Choa Chu Kang

Jurong East

Sentosa

The admin page should show this location clearly in a table.

Requirements
1️⃣ Frontend (Browser)

On login button click:

Use browser geolocation API

Request user permission

Capture latitude and longitude

Send { lat, lon, source: "browser" } to backend

If user denies permission:

Send { source: "none" }

2️⃣ Backend (Flask)

Receive lat / lon during login

If lat/lon exist:

Perform reverse geocoding using OpenStreetMap Nominatim

Convert coordinates into:

area (e.g. suburb / town / neighbourhood)

address_text (full display name)

Store all of the following in login_events:

lat

lon

location_source

area

address_text

3️⃣ Database (SQLite)

Extend login_events table with:

area TEXT
address_text TEXT


(OK to recreate DB since this is early stage.)

4️⃣ Admin Page

Show ALL login records in a table

Add columns:

Area (e.g. Jurong East)

Address (full location text)

Keep existing filter-by-username feature

Sort by latest login time

Important Notes

Page is served from Flask (http://127.0.0.1:5000/) to avoid browser geolocation issues

Geolocation requires explicit user permission

Laptop may return coarse or empty location; mobile testing may be more accurate

Use a valid User-Agent header when calling Nominatim