"""
RBAC Seeder: Populates initial SystemModule, SubModule, Role, and RolePermission records
communicating directly with PostgreSQL.
"""
from users.models import Role, SystemModule, SubModule, RolePermission, Category, User

DEFAULT_MODULES = [
    {
        'code': 'fd_registration',
        'name': 'Patients Registration',
        'icon': 'fa-user-plus',
        'color': '#4e73df',
        'primary_tab': 'patients',
        'order': 1,
        'description': 'Patient registration, Excel patient import, registered today, sponsors and coverage plans',
        'submodules': [
            {'code': 'fdRegNew', 'name': 'Register New Patient', 'icon': 'fa-user-plus', 'tab_key': 'patients', 'route': '/patients/register', 'order': 1},
            {'code': 'fdRegImport', 'name': 'Import Patient from Excel', 'icon': 'fa-file-excel', 'tab_key': 'patients', 'route': '/patients/import', 'order': 2},
            {'code': 'fdRegToday', 'name': 'Registered Today', 'icon': 'fa-calendar-day', 'tab_key': 'patients', 'route': '/patients/today', 'order': 3},
            {'code': 'fdRegSponsors', 'name': 'Sponsors Management', 'icon': 'fa-building', 'tab_key': 'tariffs', 'sub_tab': 'sponsors', 'sub_sub_tab': 'manage_sponsors', 'route': '/tariffs/sponsors', 'order': 4},
            {'code': 'fdRegPlans', 'name': 'Coverage Plans', 'icon': 'fa-layer-group', 'tab_key': 'tariffs', 'sub_tab': 'plans', 'sub_sub_tab': 'manage_plans', 'route': '/tariffs/plans', 'order': 5},
        ]
    },
    {
        'code': 'fd_records',
        'name': 'Patients Records',
        'icon': 'fa-users',
        'color': '#36b9cc',
        'primary_tab': 'patients',
        'order': 2,
        'description': 'Complete patient registry, active/inactive records, waiting lists, family folders, ANC & insurance',
        'submodules': [
            {'code': 'fdRecAll', 'name': 'All Registered Patients', 'icon': 'fa-hospital-user', 'tab_key': 'patients', 'sub_tab': 'all', 'route': '/patients/all', 'order': 1},
            {'code': 'fdRecActive', 'name': 'Active Patients', 'icon': 'fa-user-check', 'tab_key': 'patients', 'sub_tab': 'active', 'route': '/patients/active', 'order': 2},
            {'code': 'fdRecInactive', 'name': 'Deactivated Patients', 'icon': 'fa-user-slash', 'tab_key': 'patients', 'sub_tab': 'inactive', 'route': '/patients/inactive', 'order': 3},
            {'code': 'fdRecSearch', 'name': 'Search Patients Directory', 'icon': 'fa-search', 'tab_key': 'patients', 'sub_tab': 'all', 'route': '/patients/search', 'order': 4},
            {'code': 'fdRecWaiting', 'name': 'Doctors Waiting List', 'icon': 'fa-clock', 'tab_key': 'queues', 'route': '/queues/waiting', 'order': 5},
            {'code': 'fdRecBirthdays', 'name': "Today's Birthday List", 'icon': 'fa-birthday-cake', 'tab_key': 'patients', 'route': '/patients/birthdays', 'order': 6},
            {'code': 'fdRecFamily', 'name': 'Family Folders & Groups', 'icon': 'fa-folder-open', 'tab_key': 'family-folders', 'route': '/patients/family', 'order': 7},
            {'code': 'fdRecANC', 'name': 'ANC Patients List', 'icon': 'fa-baby', 'tab_key': 'anc', 'route': '/patients/anc', 'order': 8},
            {'code': 'fdRecHMO', 'name': 'HMO Patients', 'icon': 'fa-id-card', 'tab_key': 'patients', 'route': '/patients/hmo', 'order': 9},
            {'code': 'fdRecNHIS', 'name': 'NHIS Patients', 'icon': 'fa-shield-alt', 'tab_key': 'patients', 'route': '/patients/nhis', 'order': 10},
            {'code': 'fdRecRetain', 'name': 'Retainership Patients', 'icon': 'fa-briefcase', 'tab_key': 'patients', 'route': '/patients/retainership', 'order': 11},
        ]
    },
    {
        'code': 'fd_appointments',
        'name': 'Appointments',
        'icon': 'fa-bell',
        'color': '#f6c23e',
        'primary_tab': 'appointments',
        'order': 3,
        'description': 'Appointment scheduling, calendar queues, cancellation tracker, visit purposes and diagnoses directory',
        'submodules': [
            {'code': 'fdAppToday', 'name': "Today's Appointments", 'icon': 'fa-calendar-check', 'tab_key': 'appointments', 'sub_tab': 'today', 'route': '/appointments/today', 'order': 1},
            {'code': 'fdAppUpcoming', 'name': 'Upcoming Appointments', 'icon': 'fa-calendar-alt', 'tab_key': 'appointments', 'sub_tab': 'upcoming', 'route': '/appointments/upcoming', 'order': 2},
            {'code': 'fdAppCancelled', 'name': 'Cancelled Appointments', 'icon': 'fa-calendar-times', 'tab_key': 'appointments', 'sub_tab': 'cancelled', 'route': '/appointments/cancelled', 'order': 3},
            {'code': 'fdAppReviews', 'name': 'Appointments Reviews & All', 'icon': 'fa-notes-medical', 'tab_key': 'appointments', 'sub_tab': 'all', 'route': '/appointments/all', 'order': 4},
            {'code': 'fdAppPurposes', 'name': 'Visit Purposes Setup', 'icon': 'fa-stethoscope', 'tab_key': 'visit-purposes', 'route': '/setup/visit-purposes', 'order': 5},
            {'code': 'fdAppDiagnoses', 'name': 'Medical Diagnoses Directory', 'icon': 'fa-book-medical', 'tab_key': 'diagnoses-setup', 'route': '/setup/diagnoses', 'order': 6},
            {'code': 'fdAppComplaints', 'name': 'Presenting Complaints Directory', 'icon': 'fa-clipboard-list', 'tab_key': 'complaints-setup', 'route': '/setup/complaints', 'order': 7},
        ]
    },
    {
        'code': 'fd_attendance',
        'name': 'Attendance Sheet',
        'icon': 'fa-clipboard-list',
        'color': '#20c997',
        'primary_tab': 'queues',
        'order': 4,
        'description': 'Patient check-ins, queue logs, and all-time clinic attendance register',
        'submodules': [
            {'code': 'fdAttAll', 'name': 'All-time Attendance', 'icon': 'fa-clipboard-check', 'tab_key': 'queues', 'route': '/attendance/all', 'order': 1},
        ]
    },
    {
        'code': 'fd_uploads',
        'name': 'File Uploads',
        'icon': 'fa-upload',
        'color': '#6f42c1',
        'primary_tab': 'tariffs',
        'order': 5,
        'description': 'Excel bulk upload for patient types, patient records, and hospital service price schedules',
        'submodules': [
            {'code': 'fdUpPlans', 'name': 'Upload Patient Types', 'icon': 'fa-file-upload', 'tab_key': 'tariffs', 'sub_tab': 'packages', 'route': '/uploads/plans', 'order': 1},
            {'code': 'fdUpRecords', 'name': 'Upload Patient Records', 'icon': 'fa-users-cog', 'tab_key': 'patients', 'route': '/uploads/records', 'order': 2},
            {'code': 'fdUpServices', 'name': 'Upload Service List', 'icon': 'fa-list-alt', 'tab_key': 'tariffs', 'sub_tab': 'service', 'route': '/uploads/services', 'order': 3},
        ]
    },
    {
        'code': 'fd_billing',
        'name': 'Billings Clearance',
        'icon': 'fa-money-bill-wave',
        'color': '#28a745',
        'primary_tab': 'billings',
        'order': 6,
        'description': 'Front desk encounter point-of-sale billing, invoice generation, receipts & patient deposit accounts',
        'submodules': [
            {'code': 'fdBillEnc', 'name': 'Encounter Billing Queue', 'icon': 'fa-cash-register', 'tab_key': 'billings', 'route': '/billings/encounters', 'order': 1},
            {'code': 'fdBillInv', 'name': 'Invoices Management', 'icon': 'fa-file-invoice-dollar', 'tab_key': 'billings', 'route': '/billings/invoices', 'order': 2},
            {'code': 'fdBillRec', 'name': 'Payment Receipts', 'icon': 'fa-receipt', 'tab_key': 'billings', 'route': '/billings/receipts', 'order': 3},
            {'code': 'fdBillDep', 'name': 'Customer Deposit Accounts', 'icon': 'fa-wallet', 'tab_key': 'billings', 'route': '/billings/deposits', 'order': 4},
        ]
    },
    {
        'code': 'nursing',
        'name': 'Nursing Station',
        'icon': 'fa-user-nurse',
        'color': '#1cc88a',
        'primary_tab': 'queues',
        'order': 7,
        'description': 'Nurse triage, patient waiting lists, vital signs, ward beds & inpatient admissions',
        'submodules': [
            {'code': 'nrVitals', 'name': 'Nurse Triage & Vitals', 'icon': 'fa-heartbeat', 'tab_key': 'queues', 'route': '/queues/vitals', 'order': 1},
            {'code': 'nrQueues', 'name': 'Patient Waiting List', 'icon': 'fa-clock', 'tab_key': 'queues', 'route': '/queues/waiting', 'order': 2},
            {'code': 'nrBeds', 'name': 'Ward Beds & Admissions', 'icon': 'fa-bed', 'tab_key': 'ipd', 'route': '/ipd/beds', 'order': 3},
            {'code': 'nrANC', 'name': 'Antenatal Triage', 'icon': 'fa-baby', 'tab_key': 'anc', 'route': '/anc', 'order': 4},
            {'code': 'nrPatients', 'name': 'Registered Patients', 'icon': 'fa-hospital-user', 'tab_key': 'patients', 'route': '/patients/all', 'order': 5},
        ]
    },
    {
        'code': 'clinical',
        'name': 'Clinical & Consultations',
        'icon': 'fa-user-md',
        'color': '#36b9cc',
        'primary_tab': 'queues',
        'order': 8,
        'description': 'Doctor consultations, medical diagnoses, diagnostic test ordering & lab/scan results',
        'submodules': [
            {'code': 'clQueues', 'name': 'Doctor Consultation Queue', 'icon': 'fa-stethoscope', 'tab_key': 'queues', 'route': '/queues/doctor', 'order': 1},
            {'code': 'clDiagnoses', 'name': 'Medical Diagnoses Setup', 'icon': 'fa-book-medical', 'tab_key': 'diagnoses-setup', 'route': '/setup/diagnoses', 'order': 2},
            {'code': 'clComplaints', 'name': 'Presenting Complaints Setup', 'icon': 'fa-clipboard-list', 'tab_key': 'complaints-setup', 'route': '/setup/complaints', 'order': 3},
            {'code': 'clRadioLab', 'name': 'Laboratory & Scan Orders', 'icon': 'fa-flask', 'tab_key': 'radiolab', 'route': '/orders/radiolab', 'order': 4},
            {'code': 'clAppointments', 'name': 'Clinical Appointments', 'icon': 'fa-calendar-check', 'tab_key': 'appointments', 'route': '/appointments/all', 'order': 5},
            {'code': 'clPatients', 'name': 'Patient Health Directory', 'icon': 'fa-user-injured', 'tab_key': 'patients', 'route': '/patients/all', 'order': 6},
        ]
    },
    {
        'code': 'inventory',
        'name': 'Inventory & Store',
        'icon': 'fa-boxes',
        'color': '#f6c23e',
        'primary_tab': 'inventory',
        'order': 9,
        'description': 'Hospital stock catalog, vendor management, internal pharmacy transfers & store requisitions',
        'submodules': [
            {'code': 'invCatalog', 'name': 'Stock & Products Catalog', 'icon': 'fa-box-open', 'tab_key': 'inventory', 'sub_tab': 'view', 'route': '/inventory/catalog', 'order': 1},
            {'code': 'invTransfers', 'name': 'Internal Stock Transfers', 'icon': 'fa-exchange-alt', 'tab_key': 'inventory', 'sub_tab': 'transfer', 'route': '/inventory/transfers', 'order': 2},
            {'code': 'invRequests', 'name': 'Store Product Requisitions', 'icon': 'fa-dolly', 'tab_key': 'inventory', 'sub_tab': 'request', 'route': '/inventory/requests', 'order': 3},
            {'code': 'invVendors', 'name': 'Vendors & Suppliers', 'icon': 'fa-truck', 'tab_key': 'inventory', 'sub_tab': 'vendor', 'route': '/inventory/vendors', 'order': 4},
            {'code': 'invLog', 'name': 'Inventory Audit Logs', 'icon': 'fa-clipboard-check', 'tab_key': 'inventory', 'sub_tab': 'log', 'route': '/inventory/logs', 'order': 5},
        ]
    },
    {
        'code': 'ipd_pharmacy',
        'name': 'Inpatient Pharmacy (IPD)',
        'icon': 'fa-pills',
        'color': '#e74a3b',
        'primary_tab': 'ipd',
        'order': 10,
        'description': 'Inpatient drug chart dispensing, ward stock allocations & IPD pharmacy stores 1, 2, 3',
        'submodules': [
            {'code': 'ipdPresc', 'name': 'Inpatient Drug Charts', 'icon': 'fa-prescription', 'tab_key': 'ipd', 'route': '/pharmacy/ipd/charts', 'order': 1},
            {'code': 'ipdAlloc', 'name': 'Ward Stock Allocations', 'icon': 'fa-procedures', 'tab_key': 'ipd', 'route': '/pharmacy/ipd/allocations', 'order': 2},
            {'code': 'ipdDispense', 'name': 'Bedside Dispensing', 'icon': 'fa-pills', 'tab_key': 'ipd', 'route': '/pharmacy/ipd/dispense', 'order': 3},
        ]
    },
    {
        'code': 'opd_pharmacy',
        'name': 'Outpatient Pharmacy (OPD)',
        'icon': 'fa-capsules',
        'color': '#6f42c1',
        'primary_tab': 'pharmacy',
        'order': 11,
        'description': 'Outpatient prescription dispensing, drug price catalog & cashier medication clearance',
        'submodules': [
            {'code': 'opdPresc', 'name': 'Outpatient Prescriptions', 'icon': 'fa-capsules', 'tab_key': 'pharmacy', 'route': '/pharmacy/opd/prescriptions', 'order': 1},
            {'code': 'opdDispense', 'name': 'Medication Dispensing Queue', 'icon': 'fa-tablets', 'tab_key': 'pharmacy', 'route': '/pharmacy/opd/dispense', 'order': 2},
            {'code': 'opdCatalog', 'name': 'Drug Price Catalog', 'icon': 'fa-list-ol', 'tab_key': 'pharmacy', 'route': '/pharmacy/catalog', 'order': 3},
        ]
    },
    {
        'code': 'laboratory',
        'name': 'Laboratory Unit',
        'icon': 'fa-flask',
        'color': '#fd7e14',
        'primary_tab': 'radiolab',
        'order': 12,
        'description': 'Pathology test waiting queues, specimen results recording & validated test reports',
        'submodules': [
            {'code': 'labQueue', 'name': 'Specimen Testing Queue', 'icon': 'fa-vial', 'tab_key': 'radiolab', 'route': '/lab/queue', 'order': 1},
            {'code': 'labResults', 'name': 'Pathology Results Entry', 'icon': 'fa-edit', 'tab_key': 'radiolab', 'route': '/lab/results', 'order': 2},
            {'code': 'labReports', 'name': 'Validated Test Reports', 'icon': 'fa-file-medical-alt', 'tab_key': 'radiolab', 'route': '/lab/reports', 'order': 3},
            {'code': 'labTariffs', 'name': 'Laboratory Fee Schedule', 'icon': 'fa-tag', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'lab_charges', 'route': '/tariffs/lab', 'order': 4},
        ]
    },
    {
        'code': 'radiology',
        'name': 'Radiology & Imaging',
        'icon': 'fa-x-ray',
        'color': '#20c997',
        'primary_tab': 'radiolab',
        'order': 13,
        'description': 'X-Ray, Ultrasound, scan order queue, image review & diagnostic imaging impressions',
        'submodules': [
            {'code': 'radioQueue', 'name': 'Imaging Order Queue', 'icon': 'fa-x-ray', 'tab_key': 'radiolab', 'route': '/radiology/queue', 'order': 1},
            {'code': 'radioUpload', 'name': 'Scan & X-Ray Uploads', 'icon': 'fa-upload', 'tab_key': 'radiolab', 'route': '/radiology/upload', 'order': 2},
            {'code': 'radioReports', 'name': 'Radiology Impressions', 'icon': 'fa-notes-medical', 'tab_key': 'radiolab', 'route': '/radiology/impressions', 'order': 3},
            {'code': 'radioTariffs', 'name': 'Imaging Fee Schedule', 'icon': 'fa-tag', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'radiology_charges', 'route': '/tariffs/radiology', 'order': 4},
        ]
    },
    {
        'code': 'billings',
        'name': 'Billings & Accounts',
        'icon': 'fa-money-bill-wave',
        'color': '#28a745',
        'primary_tab': 'billings',
        'order': 14,
        'description': 'Patient invoices, payment receipts, customer deposit accounts, refunds & transactions',
        'submodules': [
            {'code': 'billEncounters', 'name': 'Encounter Billing Queue', 'icon': 'fa-cash-register', 'tab_key': 'billings', 'route': '/billings/encounters', 'order': 1},
            {'code': 'billInvoices', 'name': 'Invoices Management', 'icon': 'fa-file-invoice-dollar', 'tab_key': 'billings', 'route': '/billings/invoices', 'order': 2},
            {'code': 'billReceipts', 'name': 'Payment Receipts', 'icon': 'fa-receipt', 'tab_key': 'billings', 'route': '/billings/receipts', 'order': 3},
            {'code': 'billDeposits', 'name': 'Customer Deposit Accounts', 'icon': 'fa-wallet', 'tab_key': 'billings', 'route': '/billings/deposits', 'order': 4},
            {'code': 'billRefunds', 'name': 'Patient Refunds', 'icon': 'fa-hand-holding-usd', 'tab_key': 'billings', 'route': '/billings/refunds', 'order': 5},
        ]
    },
    {
        'code': 'anc',
        'name': 'Antenatal Care (ANC)',
        'icon': 'fa-baby',
        'color': '#e83e8c',
        'primary_tab': 'anc',
        'order': 15,
        'description': 'Maternal health registration, antenatal booking, clinic visits & gestation records',
        'submodules': [
            {'code': 'ancBooking', 'name': 'ANC Patient Booking', 'icon': 'fa-user-check', 'tab_key': 'anc', 'route': '/anc/booking', 'order': 1},
            {'code': 'ancVisits', 'name': 'Antenatal Visits & Vitals', 'icon': 'fa-stethoscope', 'tab_key': 'anc', 'route': '/anc/visits', 'order': 2},
            {'code': 'ancGestation', 'name': 'Gestation & Ultrasound', 'icon': 'fa-file-medical', 'tab_key': 'anc', 'route': '/anc/gestation', 'order': 3},
        ]
    },
    {
        'code': 'reporting',
        'name': 'Reporting & Analytics',
        'icon': 'fa-chart-line',
        'color': '#6610f2',
        'primary_tab': 'reporting',
        'order': 16,
        'description': 'Ambulatory, in-patient, hospital revenue, diagnosis sheets & government health returns',
        'submodules': [
            {'code': 'repAmbulatory', 'name': 'Ambulatory Health Returns', 'icon': 'fa-ambulance', 'tab_key': 'reporting', 'sub_tab': 'ambulatory', 'route': '/reporting/ambulatory', 'order': 1},
            {'code': 'repInpatient', 'name': 'Inpatient Care Reports', 'icon': 'fa-procedures', 'tab_key': 'reporting', 'sub_tab': 'inpatient', 'route': '/reporting/inpatient', 'order': 2},
            {'code': 'repRevenue', 'name': 'Hospital Revenue Reports', 'icon': 'fa-chart-line', 'tab_key': 'reporting', 'sub_tab': 'revenue', 'route': '/reporting/revenue', 'order': 3},
            {'code': 'repDiagnosis', 'name': 'Medical Diagnosis Sheets', 'icon': 'fa-diagnoses', 'tab_key': 'reporting', 'sub_tab': 'diagnosis', 'route': '/reporting/diagnosis', 'order': 4},
            {'code': 'repInventory', 'name': 'Inventory Stock Reports', 'icon': 'fa-boxes', 'tab_key': 'reporting', 'sub_tab': 'inventory', 'route': '/reporting/inventory', 'order': 5},
            {'code': 'repAppointments', 'name': 'Appointments Reports', 'icon': 'fa-calendar', 'tab_key': 'reporting', 'sub_tab': 'others', 'route': '/reporting/appointments', 'order': 6},
        ]
    },
    {
        'code': 'taskmanager',
        'name': 'Task Manager (Admin Tools)',
        'icon': 'fa-tasks',
        'color': '#4e73df',
        'primary_tab': 'taskmanager',
        'order': 17,
        'description': 'Staff directory, account credentials, online user sessions & system activities audit',
        'submodules': [
            {'code': 'tmStaff', 'name': 'Staff Directory & Management', 'icon': 'fa-users-cog', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'manage_users', 'route': '/admin/staff', 'order': 1},
            {'code': 'tmOnline', 'name': 'Active Online Users', 'icon': 'fa-globe', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'online_users', 'route': '/admin/online', 'order': 2},
            {'code': 'tmLogs', 'name': 'User Activity Audit Logs', 'icon': 'fa-history', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'activity_logs', 'route': '/admin/audit-logs', 'order': 3},
            {'code': 'tmDashboard', 'name': 'Activities Dashboard', 'icon': 'fa-tachometer-alt', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'activity_dashboard', 'route': '/admin/dashboard', 'order': 4},
            {'code': 'tmVerify', 'name': 'Verify Staff ID', 'icon': 'fa-check-circle', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'verify_staff', 'route': '/admin/verify-staff', 'order': 5},
            {'code': 'tmCreateStaff', 'name': 'Register New Staff', 'icon': 'fa-user-plus', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'create_staff', 'route': '/admin/register-staff', 'order': 6},
            {'code': 'tmRbac', 'name': 'Department & Module Access', 'icon': 'fa-sitemap', 'tab_key': 'taskmanager', 'sub_tab': 'staff', 'sub_sub_tab': 'rbac', 'route': '/admin/departments', 'order': 7},
            {'code': 'tmQueue', 'name': 'Queue Flow Monitor', 'icon': 'fa-chart-bar', 'tab_key': 'taskmanager', 'sub_tab': 'queue', 'route': '/admin/queue-flow', 'order': 8},
            {'code': 'tmStats', 'name': 'Statistical Insights', 'icon': 'fa-lightbulb', 'tab_key': 'taskmanager', 'sub_tab': 'stats', 'route': '/admin/stats', 'order': 9},
        ]
    },
    {
        'code': 'tariffs',
        'name': 'Manage Tariff Plans',
        'icon': 'fa-tags',
        'color': '#17a2b8',
        'primary_tab': 'tariffs',
        'order': 18,
        'description': 'Service price schedules, laboratory fees, admission charges & patient care packages',
        'submodules': [
            {'code': 'trfReg', 'name': 'Registration Fees', 'icon': 'fa-id-card', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'reg_fees', 'route': '/tariffs/registration', 'order': 1},
            {'code': 'trfLab', 'name': 'Laboratory Charges', 'icon': 'fa-vial', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'lab_charges', 'route': '/tariffs/lab', 'order': 2},
            {'code': 'trfRadio', 'name': 'Radiology Charges', 'icon': 'fa-x-ray', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'radiology_charges', 'route': '/tariffs/radiology', 'order': 3},
            {'code': 'trfAdmission', 'name': 'Admission Fees', 'icon': 'fa-bed', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'admission_fees', 'route': '/tariffs/admission', 'order': 4},
            {'code': 'trfOther', 'name': 'Other Services Fees', 'icon': 'fa-hand-holding-medical', 'tab_key': 'tariffs', 'sub_tab': 'service', 'sub_sub_tab': 'other_services', 'route': '/tariffs/services', 'order': 5},
            {'code': 'trfMeds', 'name': 'Medication Fees', 'icon': 'fa-pills', 'tab_key': 'tariffs', 'sub_tab': 'product', 'sub_sub_tab': 'medication_fees', 'route': '/tariffs/medications', 'order': 6},
            {'code': 'trfPackages', 'name': 'Care Packages', 'icon': 'fa-box-open', 'tab_key': 'tariffs', 'sub_tab': 'packages', 'route': '/tariffs/packages', 'order': 7},
            {'code': 'trfSponsors', 'name': 'Sponsors & HMO Plans', 'icon': 'fa-building', 'tab_key': 'tariffs', 'sub_tab': 'sponsors', 'route': '/tariffs/sponsors', 'order': 8},
            {'code': 'trfPurposes', 'name': 'Appointment & Visit Purposes Setup', 'icon': 'fa-stethoscope', 'tab_key': 'visit-purposes', 'route': '/tariffs/visit-purposes', 'order': 9},
            {'code': 'trfDiagnoses', 'name': 'Medical Diagnoses Directory & Bulk Setup', 'icon': 'fa-book-medical', 'tab_key': 'diagnoses-setup', 'route': '/tariffs/diagnoses-setup', 'order': 10},
        ]
    },
]

ALL_SYSTEM_MODULE_CODES = [
    'fd_registration', 'fd_records', 'fd_appointments', 'fd_attendance', 'fd_uploads', 'fd_billing',
    'nursing', 'clinical', 'inventory', 'ipd_pharmacy', 'opd_pharmacy', 'laboratory',
    'radiology', 'billings', 'anc', 'reporting', 'taskmanager', 'tariffs'
]

DEFAULT_ROLE_CONFIGS = [
    {
        'name': 'Admin',
        'description': 'Super administrator with full privileges across all clinical and administrative modules',
        'is_system': True,
        'modules': ALL_SYSTEM_MODULE_CODES
    },
    {
        'name': 'CMD',
        'description': 'Chief Medical Director with comprehensive clinical, administrative, and reporting oversight',
        'is_system': True,
        'modules': ALL_SYSTEM_MODULE_CODES
    },
    {
        'name': 'Front Desk',
        'description': 'Patient reception, registration, records, appointments, attendance sheet, file uploads & billing vouchers',
        'is_system': False,
        'modules': ['fd_registration', 'fd_records', 'fd_appointments', 'fd_attendance', 'fd_uploads', 'fd_billing']
    },
    {
        'name': 'Nursing',
        'description': 'Nurse station triage, patient waiting list, ward admissions & maternal health nursing',
        'is_system': False,
        'modules': ['nursing', 'clinical', 'anc', 'ipd_pharmacy']
    },
    {
        'name': 'Clinical',
        'description': 'Doctor consultations, medical diagnoses, diagnostic test ordering & patient health charts',
        'is_system': False,
        'modules': ['clinical', 'nursing', 'laboratory', 'radiology', 'anc']
    },
    {
        'name': 'Inventory',
        'description': 'Hospital central store, stock catalog, product requisitions & vendor management',
        'is_system': False,
        'modules': ['inventory']
    },
    {
        'name': 'IPD Pharmacy 1',
        'description': 'Inpatient pharmacy store 1 for inpatient drug charts, ward dispensing & requisitions',
        'is_system': False,
        'modules': ['ipd_pharmacy', 'inventory']
    },
    {
        'name': 'IPD Pharmacy 2',
        'description': 'Inpatient pharmacy store 2 for ward stock & scheduled inpatient medication distribution',
        'is_system': False,
        'modules': ['ipd_pharmacy', 'inventory']
    },
    {
        'name': 'IPD Pharmacy 3',
        'description': 'Inpatient pharmacy store 3 for specialized inpatient care pharmaceuticals',
        'is_system': False,
        'modules': ['ipd_pharmacy', 'inventory']
    },
    {
        'name': 'OPD Pharmacy 1',
        'description': 'Outpatient dispensary store 1 for prescription dispensing & drug pricing',
        'is_system': False,
        'modules': ['opd_pharmacy', 'inventory']
    },
    {
        'name': 'OPD Pharmacy 2',
        'description': 'Outpatient dispensary store 2 for outpatient medication clearance',
        'is_system': False,
        'modules': ['opd_pharmacy', 'inventory']
    },
    {
        'name': 'Laboratory',
        'description': 'Pathology testing unit, specimen queue, results validation & lab tariff schedules',
        'is_system': False,
        'modules': ['laboratory']
    },
    {
        'name': 'Radiology',
        'description': 'Medical imaging unit, scan order queue, image review & radiology fee schedules',
        'is_system': False,
        'modules': ['radiology']
    },
    {
        'name': 'Billings Unit',
        'description': 'Hospital accounts cashier, encounter billing, invoices, receipts & customer deposits',
        'is_system': False,
        'modules': ['billings']
    },
    {
        'name': 'Reporting Unit',
        'description': 'Medical records & statistical analytics unit for ambulatory, revenue & inpatient returns',
        'is_system': False,
        'modules': ['reporting']
    },
]


def seed_rbac(force_reassign_frontdesk=True):
    """
    Ensures all default Modules, Submodules, Roles, and RolePermissions are present in the database.
    Idempotent and safe to run multiple times.
    """
    # 1. Seed System Modules & Submodules
    module_objs = {}
    submodule_objs = {}

    for mod_data in DEFAULT_MODULES:
        mod_obj, _ = SystemModule.objects.update_or_create(
            code=mod_data['code'],
            defaults={
                'name': mod_data['name'],
                'icon': mod_data.get('icon', 'fa-cubes'),
                'color': mod_data.get('color', '#4e73df'),
                'primary_tab': mod_data.get('primary_tab', 'patients'),
                'description': mod_data.get('description', ''),
                'order': mod_data.get('order', 0),
                'is_active': True,
            }
        )
        module_objs[mod_obj.code] = mod_obj

        for sub_data in mod_data.get('submodules', []):
            sub_obj, _ = SubModule.objects.update_or_create(
                module=mod_obj,
                code=sub_data['code'],
                defaults={
                    'name': sub_data['name'],
                    'icon': sub_data.get('icon', 'fa-circle'),
                    'tab_key': sub_data.get('tab_key', ''),
                    'sub_tab': sub_data.get('sub_tab', ''),
                    'sub_sub_tab': sub_data.get('sub_sub_tab', ''),
                    'route': sub_data.get('route', ''),
                    'order': sub_data.get('order', 0),
                    'is_active': True,
                }
            )
            submodule_objs[f"{mod_obj.code}.{sub_obj.code}"] = sub_obj

    # Clean up legacy frontdesk module if present
    legacy_fd = SystemModule.objects.filter(code='frontdesk').first()
    if legacy_fd:
        # Move any custom submodules or delete legacy module if now superseded
        legacy_fd.delete()

    # 2. Sync existing Categories to Roles
    categories = Category.objects.all()
    for cat in categories:
        if cat.department:
            Role.objects.get_or_create(
                name=cat.department.strip(),
                defaults={
                    'description': f'Department Role for {cat.department.strip()}',
                    'category': cat,
                }
            )

    # 3. Seed Default Roles and Permissions
    for role_cfg in DEFAULT_ROLE_CONFIGS:
        role_obj, _ = Role.objects.get_or_create(
            name=role_cfg['name'],
            defaults={
                'description': role_cfg['description'],
                'is_system': role_cfg.get('is_system', False),
            }
        )

        # If Category exists with this name, link it
        cat = Category.objects.filter(department__iexact=role_obj.name).first()
        if cat and not role_obj.category:
            role_obj.category = cat
            role_obj.save()

        # Check if permissions exist or force update for Front Desk / Admin
        should_seed_perms = not RolePermission.objects.filter(role=role_obj).exists()
        if force_reassign_frontdesk and role_obj.name.lower() in ['front desk', 'frontdesk', 'admin', 'cmd']:
            should_seed_perms = True

        if should_seed_perms:
            for mod_code in role_cfg.get('modules', []):
                mod_obj = module_objs.get(mod_code)
                if not mod_obj:
                    continue
                perm, _ = RolePermission.objects.get_or_create(role=role_obj, module=mod_obj)
                # Assign all submodules of this module by default
                all_subs = mod_obj.submodules.all()
                perm.submodules.set(all_subs)

    # 4. Link existing users to Roles
    for user in User.objects.filter(role__isnull=True):
        dept_name = user.department.department if user.department else 'Admin'
        role = Role.objects.filter(name__iexact=dept_name).first()
        if not role:
            role = Role.objects.filter(name='Admin').first()
        if role:
            user.role = role
            user.save(update_fields=['role'])

    print(f"RBAC Seed Complete: {SystemModule.objects.count()} modules, {SubModule.objects.count()} submodules, {Role.objects.count()} departments, {RolePermission.objects.count()} permissions.")

