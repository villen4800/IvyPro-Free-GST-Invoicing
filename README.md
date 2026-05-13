# 🌿 IvyPro V1
**The Next-Generation Financial Operating System for Indian Enterprises.**

IvyPro is a high-performance, keyboard-driven accounting and GST billing software designed for speed, compliance, and aesthetic excellence. It combines the power of traditional accounting logic with a state-of-the-art "Modern Dark" interface.

---

## ✨ Exhaustive Feature List

### 📦 Billing & Voucher Management
- **Smart Voucher Suite**: Dedicated entry screens for **Sales, Purchase, Payment, Receipt, Contra, Journal, and Credit/Debit Notes**.
- **Multi-Mode Billing**:
    - **Standard Invoice**: Professional Tax Invoice for B2B/B2C compliance.
    - **POS Interface**: Rapid retail entry for high-frequency transactions.
    - **Service Billing**: Specialized layout for service-based businesses.
    - **Simple Mode**: Minimized interface for non-technical users.
- **Auto-Sequence**: Customizable invoice prefixes and dynamic starting sequences.

### 📊 Accounting & Financial Intelligence
- **Tally-Style Reporting**: Real-time **Balance Sheet**, **Profit & Loss Account**, and **Detailed Trial Balance**.
- **Opening/Closing Stock**: Advanced logic for inventory-based P&L accuracy.
- **Audit Trail (Day Book)**: Chronological transaction records with filtered views.
- **Ledger Master**: Group-based accounting with instant Statement generation and running balances.

### 📦 Inventory Control
- **Dynamic Stock Tracking**: HSN/SAC code management, tax-rate assignments, and UOM support.
- **Stock Summary**: Comprehensive inward/outward movement tracking and valuation.

### 🇮🇳 GST Compliance
- **Dual Scheme Support**: Seamlessly handle **Regular** and **Composition** taxpayers.
- **Statutory Reports**: One-click generation of **GSTR-1, GSTR-3B, and GSTR-4**.
- **Tax Engine**: Automatic computation of CGST, SGST, and IGST based on supply location.

### ⌨️ Speed & Interaction
- **Keyboard-First Workflow**: Full Tally-style shortcut integration (F1-F12, Alt Keys).
- **Command Palette (Ctrl + K)**: Universal search to jump anywhere instantly.
- **Maximized View**: Native desktop integration with windowed-fullscreen startup.

---

## 🔌 Plugin Ecosystem (Power-Ups)

### Available Modules:
- **📅 Staff Attendance**: Integrated register for staff clock-in/out and payroll audits.
- **🛠️ Service Job Tracker**: Professional job card management and repair status workflow.
- **🔄 Tally Sync Engine**: Infrastructure for bi-directional data bridge with Tally.
- **✍️ CTS-2010 Cheque Master**: Precise Indian standard cheque printing from statements.

> [!CAUTION]
> ### ⚠️ Known Issues & Technical Warnings
> *   **Data Integrity**: Plugins directly modify the core financial database. **Always perform a full backup** before activation.
> *   **Authorization**: Some plugins require a unique Admin Authorization Key to enable.
> *   **Record Persistence**: Deactivating a plugin hides the interface but **does not delete data** from the database; reactivation restores all history.
> *   **Hardware Sync**: Thermal Printing and Biometric features are dependent on local driver compatibility and hardware connection.

---

## 🎨 Design Language
IvyPro features a curated **Ivy Orange** branding (`rgb(255, 116, 41)`) set against a deep-charcoal "Premium Dark" theme. Every interaction is polished with subtle micro-animations and glassmorphism.

---

## 🚀 Quick Start (Development)
1. **Prerequisites**: Python 3.8+
2. **Setup**: `pip install -r requirements.txt`
3. **Run**: `python run.py`
4. **Build**: Run `build_app.bat` to generate the standalone Windows EXE.

---

## 🏗️ Tech Stack
- **Backend**: Python / Flask / SQLAlchemy
- **Frontend**: Vanilla JS / CSS3 (High Performance)
- **Desktop**: PyWebView / PyInstaller
- **Database**: SQLite (Encrypted)

---
*Developed with precision for the modern Indian accountant.*
