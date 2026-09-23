# USCIP Portal

USCIP Portal is a Django-based comprehensive office management web application designed to streamline internal IT requests and monitor ISO 27001 compliance. 

## 🚀 Features

The system is composed of two main modules:

### 1. Office Portal (`portal` app)
A centralized hub for employees to manage their profiles and submit IT-related requests, featuring an approval workflow system.
* **User Management:** User registration, profile management, password reset, and role-based access control (e.g., General Users, Team Leaders, Hardware Supervisors).
* **Request Management:** Employees can apply for and track the status of:
  * Hardware Requests
  * Software Requests (including approval history)
  * BYOD (Bring Your Own Device) Requests
  * IT Account Requests
* **Dashboard:** A personalized dashboard to overview recent applications and pending approvals.
* **Email Notifications:** Automated email notifications (`portal/services/notify.py`) to keep users informed about their request status.

### 2. Compliance Management (`compliance` app)
A dedicated module for Information Security Management System (ISMS) tracking.
* **ISO 27001:2022 Integration:** Includes tools to import and manage ISO 27001:2022 controls (`import_iso.py`, `iso27001_2022_controls.json`).
* **Compliance Dashboard:** Visual overview of control implementation status and compliance metrics.

## 🛠️ Tech Stack

* **Backend:** Python 3, Django
* **Frontend:** HTML5, CSS (Custom styling via the `theme` app), JavaScript
* **Database:** (Configured in `uscip_project/settings.py`, defaults to SQLite for development)

## 📁 Project Structure

```text
uscip_portal/
├── compliance/         # ISO 27001 compliance tracking and dashboards
├── portal/             # Main office portal app (Requests, Users, Approvals)
├── theme/              # UI/UX theme and static assets (CSS/Images)
├── templates/          # Global and app-specific HTML templates
├── uscip_project/      # Main Django project settings and configurations
├── import_iso.py       # Script to load ISO 27001 controls into the database
├── manage.py           # Django command-line utility
└── requirements.txt    # Python dependencies
