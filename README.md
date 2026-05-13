# IvyPro V1

IvyPro is a high-performance, keyboard-driven accounting and GST billing software designed for speed, compliance, and aesthetic excellence. It combines the power of traditional accounting logic with a state-of-the-art "Modern Dark" interface.
<img width="1372" height="666" alt="splash" src="https://github.com/user-attachments/assets/203d701c-c5eb-4df6-a692-b355a31a0f17" />

---
> [!NOTE]
> ### 🧪 Beta Release (v1-beta)
> IvyPro V1 is currently in **Public Beta**. We are actively refining the engine and expanding our compliance modules.
> 
> **We need your feedback!**
> *   **Found a Bug?** Please report it via the repository's "Issues" tab.
> *   **Have a Suggestion?** We are looking for feature requests to make IvyPro the best tool for Indian accountants. 
> 
> Your input directly shapes the future of this platform.

---

## 💻 User Installation (Windows 10/11)

> [!IMPORTANT]
> ### 🖥️ System Requirements
> *   **Operating System**: Windows 10 or Windows 11 (64-bit).
> *   **Display**: 1280x800 minimum resolution recommended.

### 📥 How to Run IvyPro
1.  **Extract the Files**: Locate your `IvyProV1.zip` and extract its entire contents into a permanent folder (e.g., `C:\IvyPro`). 
    *   *Warning: Do NOT run the app directly from inside the ZIP file as it will prevent database saving.*
2.  **Launch the App**: Open the folder and double-click on **`IvyProV1.exe`**.
3.  **Bypass SmartScreen**: If Windows Defender shows a "Windows protected your PC" message, click **More Info** and then **Run anyway**.
4.  **First-Time Setup**: On the first launch, the app will open in fullscreen. Follow the "First Setup" prompts to create your Administrator account and initialize your company database.

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
- **Whatsapp sharing**: whatsapp sharing intigration

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

## 🏗️ Tech Stack
- **Backend**: Python / Flask / SQLAlchemy
- **Frontend**: Vanilla JS / CSS3 (High Performance)
- **Desktop**: PyWebView / PyInstaller
- **Database**: SQLite (Encrypted)

---
*Developed with precision for the modern Indian accountant.*
